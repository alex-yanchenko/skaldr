import errno
import os
import re
import socket
import time
from urllib.parse import parse_qs, urlsplit

import httpx2
import keyring
import pytest
from keyring.errors import KeyringError

from skaldr.auth import notion as notion_module
from skaldr.auth.notion import (
    revoke_notion_token,
    save_notion_replacing_the_old_sign_in,
    save_or_revoke_notion,
    sign_in_to_notion,
)
from skaldr.auth.store import NotionCredentials
from skaldr.errors import AuthError
from tests.factories.auth_factory import (
    TOKEN_RESPONSE,
    WORKSPACE_ID,
    FakeBrowser,
    InMemoryKeyring,
    Visit,
    WriteFailingKeyring,
    answerless,
    approving,
    approving_without_state,
    assert_secret_not_in_error_chain,
    basic_auth_header,
    fake_api,
    favicon,
    forged,
    forged_refusal,
    free_port,
    make_notion_credentials,
    needs_ipv6_loopback,
    refusing,
    refusing_connections,
    refusing_with_an_escape_sequence,
    refusing_without_state,
    revoke_request_for,
    summarise,
)


def sign_in(
    browser: FakeBrowser,
    seen: list[httpx2.Request] | None = None,
    *,
    token: tuple[int, object] = (200, TOKEN_RESPONSE),
    transport: httpx2.BaseTransport | None = None,
    port: int | None = None,
    timeout_seconds: float = 5,
) -> NotionCredentials:
    return sign_in_to_notion(
        "client-id",
        "client-secret",
        open_browser=browser,
        port=free_port() if port is None else port,
        transport=transport or fake_api({"/v1/oauth/token": token}, [] if seen is None else seen),
        timeout_seconds=timeout_seconds,
    )


def test_sign_in_exchanges_the_code_with_basic_auth_and_a_json_body() -> None:
    seen: list[httpx2.Request] = []
    browser = FakeBrowser(approving)

    credentials = sign_in(browser, seen)

    assert credentials == make_notion_credentials(access_token="new-access", refresh_token="new-refresh")
    assert browser.finished() == [200]
    authorize = urlsplit(browser.opened[0])
    assert (authorize.scheme, authorize.netloc, authorize.path) == (
        "https",
        "api.notion.com",
        "/v1/oauth/authorize",
    )
    query = parse_qs(authorize.query)
    assert len(query["state"][0]) >= 43
    assert query == {
        "response_type": ["code"],
        "client_id": ["client-id"],
        "redirect_uri": [browser.redirect_uri],
        "state": query["state"],
        "owner": ["user"],
    }
    assert re.fullmatch(r"http://localhost:\d+/callback", browser.redirect_uri)
    assert [summarise(request) for request in seen] == [
        {
            "method": "POST",
            "url": "https://api.notion.com/v1/oauth/token",
            "authorization": basic_auth_header("client-id", "client-secret"),
            "content_type": "application/json",
            "body": {
                "grant_type": "authorization_code",
                "code": "the-code",
                "redirect_uri": browser.redirect_uri,
            },
        }
    ]


def test_stray_requests_are_turned_away_until_the_real_callback_arrives() -> None:
    seen: list[httpx2.Request] = []
    browser = FakeBrowser(favicon, answerless, forged, approving)

    credentials = sign_in(browser, seen)

    assert credentials == make_notion_credentials(access_token="new-access", refresh_token="new-refresh")
    assert browser.finished() == [404, 400, 400, 200]
    assert len(seen) == 1


@pytest.mark.parametrize(
    "address", ["127.0.0.1", pytest.param("::1", marks=needs_ipv6_loopback)], ids=["ipv4", "ipv6"]
)
def test_the_callback_arrives_whichever_loopback_address_localhost_resolves_to(address: str) -> None:
    browser = FakeBrowser(approving, resolves_localhost_to=address)

    credentials = sign_in(browser, port=free_port())

    assert credentials == make_notion_credentials(access_token="new-access", refresh_token="new-refresh")
    assert browser.finished() == [200]


def ipv6_bind_failing_with(code: int) -> type:
    class FailingIPv6Server:
        def __init__(self, *_args: object) -> None:
            raise OSError(code, os.strerror(code))

    return FailingIPv6Server


@pytest.mark.parametrize("code", [errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT], ids=["no ::1 address", "no ipv6"])
def test_a_machine_without_an_ipv6_loopback_listens_on_ipv4_alone(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    monkeypatch.setattr(notion_module, "_IPv6LoopbackServer", ipv6_bind_failing_with(code))
    browser = FakeBrowser(approving, resolves_localhost_to="127.0.0.1")

    credentials = sign_in(browser)

    assert credentials == make_notion_credentials(access_token="new-access", refresh_token="new-refresh")
    assert browser.finished() == [200]


def test_any_other_ipv6_bind_failure_stops_the_sign_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_module, "_IPv6LoopbackServer", ipv6_bind_failing_with(errno.EACCES))

    with pytest.raises(
        AuthError, match=r"^Cannot listen on \[::1\]:\d+ \(Permission denied\); free the port"
    ):
        sign_in(FakeBrowser(), timeout_seconds=0.2)


def test_a_second_matching_callback_is_turned_away() -> None:
    browser = FakeBrowser(approving, approving)

    def answer_after_both_visits(_request: httpx2.Request) -> httpx2.Response:
        deadline = time.monotonic() + 5
        while len(browser.statuses) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        return httpx2.Response(200, json=TOKEN_RESPONSE)

    credentials = sign_in(browser, transport=httpx2.MockTransport(answer_after_both_visits))

    assert credentials == make_notion_credentials(access_token="new-access", refresh_token="new-refresh")
    assert browser.finished() == [200, 409]


@pytest.mark.parametrize(
    "visit",
    [forged, answerless, forged_refusal, refusing_without_state, approving_without_state],
    ids=[
        "forged state",
        "no code or error",
        "forged refusal",
        "a refusal without a state",
        "a code without a state",
    ],
)
def test_a_callback_that_does_not_answer_this_sign_in_never_reaches_the_token_endpoint(visit: Visit) -> None:
    seen: list[httpx2.Request] = []
    browser = FakeBrowser(visit)

    with pytest.raises(AuthError, match=r"^Timed out after 2 seconds waiting for Notion"):
        sign_in(browser, seen, timeout_seconds=2)

    assert (browser.finished(), seen) == ([400], [])


def test_a_refusal_without_a_state_does_not_end_the_wait_for_the_real_callback() -> None:
    browser = FakeBrowser(refusing_without_state, approving)

    credentials = sign_in(browser)

    assert credentials == make_notion_credentials(access_token="new-access", refresh_token="new-refresh")
    assert browser.finished() == [400, 200]


@pytest.mark.parametrize(
    ("visit", "message"),
    [
        (refusing, "Notion did not grant access: access_denied"),
        (refusing_with_an_escape_sequence, "Notion did not grant access"),
    ],
    ids=["an oauth error code", "an error that is not an oauth error code"],
)
def test_a_refused_consent_screen_stops_the_sign_in(visit: Visit, message: str) -> None:
    seen: list[httpx2.Request] = []
    browser = FakeBrowser(visit)

    with pytest.raises(AuthError) as raised:
        sign_in(browser, seen)

    assert (str(raised.value), browser.finished(), seen) == (message, [200], [])


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (
            {"error": "invalid_client"},
            "Notion refused the client ID or secret (invalid_client); copy both from the connection page "
            "at https://www.notion.so/profile/integrations again",
        ),
        (
            {"error": "invalid_grant", "error_description": "code expired"},
            "Notion refused the sign-in: invalid_grant (code expired)",
        ),
        (
            {"error": "invalid\x1b[2J_grant", "error_description": "code\x1b]0;title\x07 expired\r\n"},
            "Notion refused the sign-in: invalid[2J_grant (code]0;title expired)",
        ),
        (
            {"error": "\x1b\x07", "error_description": "\x1b\r\n"},
            "Notion refused the sign-in: (unnamed error)",
        ),
    ],
    ids=[
        "error only",
        "error with a description",
        "control characters in the error and description",
        "nothing but control characters",
    ],
)
def test_a_refused_token_request_names_the_oauth_error(answer: dict[str, str], message: str) -> None:
    with pytest.raises(AuthError) as raised:
        sign_in(FakeBrowser(approving), token=(400, answer))

    assert str(raised.value) == message


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (429, {"object": "error", "status": 429, "code": "rate_limited"}),
        (403, b"<html>proxy</html>"),
        (503, {"error": "temporarily_unavailable"}),
    ],
    ids=["rate limited", "a proxy page", "a server error"],
)
def test_a_failed_token_request_without_an_oauth_error_names_the_status(status: int, body: object) -> None:
    with pytest.raises(AuthError) as raised:
        sign_in(FakeBrowser(approving), token=(status, body))

    assert str(raised.value) == f"Notion answered HTTP {status} for the token request"


@pytest.mark.parametrize(
    ("answer", "fields"),
    [
        ({"refresh_token": "secret-refresh-value", "workspace_id": WORKSPACE_ID}, "access_token"),
        (["secret-refresh-value"], "(the whole answer)"),
    ],
    ids=["no access token", "not an object"],
)
def test_a_token_answer_with_bad_fields_names_them_and_not_the_tokens(answer: object, fields: str) -> None:
    with pytest.raises(AuthError) as raised:
        sign_in(FakeBrowser(approving), token=(200, answer))

    assert str(raised.value) == f"Notion's token answer is missing or has invalid fields: {fields}"
    assert_secret_not_in_error_chain(raised.value, "secret-refresh-value")


WITHOUT_A_WORKSPACE_ID = {key: value for key, value in TOKEN_RESPONSE.items() if key != "workspace_id"}
REFUSED_WORKSPACE_ID = "Notion's token answer is missing or has invalid fields: workspace_id"


@pytest.mark.parametrize(
    "answer",
    [
        WITHOUT_A_WORKSPACE_ID,
        {**TOKEN_RESPONSE, "workspace_id": None},
        {**TOKEN_RESPONSE, "workspace_id": "not-a-uuid"},
        {**TOKEN_RESPONSE, "workspace_id": "a\x1b[2Jb"},
    ],
    ids=["missing", "null", "not a uuid", "an escape sequence"],
)
def test_a_token_answer_without_a_usable_workspace_id_has_its_token_revoked_before_it_is_refused(
    answer: dict[str, object],
) -> None:
    seen: list[httpx2.Request] = []
    routes: dict[str, tuple[int, object]] = {
        "/v1/oauth/token": (200, answer),
        "/v1/oauth/revoke": (200, {}),
    }

    with pytest.raises(AuthError) as raised:
        sign_in(FakeBrowser(approving), transport=fake_api(routes, seen))

    assert (str(raised.value), [summarise(request) for request in seen if "revoke" in request.url.path]) == (
        f"{REFUSED_WORKSPACE_ID}. The token Notion issued has been revoked.",
        [revoke_request_for("new-access")],
    )


def test_a_token_answer_without_a_workspace_id_whose_revoke_fails_says_to_remove_the_connection() -> None:
    routes: dict[str, tuple[int, object]] = {
        "/v1/oauth/token": (200, WITHOUT_A_WORKSPACE_ID),
        "/v1/oauth/revoke": (400, {}),
    }

    with pytest.raises(AuthError) as raised:
        sign_in(FakeBrowser(approving), transport=fake_api(routes, []))

    assert str(raised.value) == (
        f"{REFUSED_WORKSPACE_ID}. The token Notion issued could not be revoked (Notion did not revoke the "
        "token: HTTP 400), so remove the connection in Notion under Settings, Connections."
    )


def test_an_unreadable_index_after_the_oauth_exchange_revokes_the_token_it_cannot_save(
    keychain: InMemoryKeyring,
) -> None:
    keychain.entries[("skaldr", "index")] = "not json"
    seen: list[httpx2.Request] = []

    with pytest.raises(AuthError) as raised:
        save_notion_replacing_the_old_sign_in(ISSUED, transport=revoke_answering(200, seen))

    assert (str(raised.value), [summarise(request) for request in seen], keychain.entries) == (
        "The keychain index that lists the skaldr sign-ins is unreadable; remove the keychain entry named "
        "index under skaldr, then name each Jira site or Notion workspace to find its sign-in again. "
        "The token Notion issued has been revoked.",
        [revoke_request_for("new-access")],
        {("skaldr", "index"): "not json"},
    )


def test_a_token_answer_that_is_not_json_is_named() -> None:
    with pytest.raises(AuthError, match=r"^Notion's token answer is not JSON$"):
        sign_in(FakeBrowser(approving), token=(200, b"<html>maintenance</html>"))


def test_an_unreachable_token_endpoint_is_named() -> None:
    with pytest.raises(AuthError, match=r"^Could not reach Notion: connection refused$"):
        sign_in(FakeBrowser(approving), transport=refusing_connections())


def test_sign_in_times_out_when_the_browser_never_comes_back() -> None:
    with pytest.raises(AuthError, match=r"^Timed out after 0\.2 seconds .*; run `skaldr auth notion` again$"):
        sign_in(FakeBrowser(), timeout_seconds=0.2)


@pytest.mark.parametrize(
    ("family", "address", "shown"),
    [
        (socket.AF_INET, "127.0.0.1", r"127\.0\.0\.1"),
        pytest.param(socket.AF_INET6, "::1", r"\[::1\]", marks=needs_ipv6_loopback),
    ],
    ids=["ipv4", "ipv6"],
)
def test_a_busy_callback_port_is_named(family: socket.AddressFamily, address: str, shown: str) -> None:
    with socket.create_server((address, free_port()), family=family) as blocker:
        port = blocker.getsockname()[1]

        with pytest.raises(AuthError, match=rf"^Cannot listen on {shown}:{port} \(.+\); free the port"):
            sign_in(FakeBrowser(), port=port, timeout_seconds=0.2)


def test_revoke_sends_the_access_token_with_basic_auth() -> None:
    seen: list[httpx2.Request] = []

    revoke_notion_token(make_notion_credentials(), transport=fake_api({"/v1/oauth/revoke": (200, {})}, seen))

    assert [summarise(request) for request in seen] == [
        {
            "method": "POST",
            "url": "https://api.notion.com/v1/oauth/revoke",
            "authorization": basic_auth_header("client-id", "client-secret"),
            "content_type": "application/json",
            "body": {"token": "access-token"},
        }
    ]


@pytest.mark.parametrize("missing", ["client_id", "client_secret"])
def test_a_token_without_its_client_cannot_be_revoked(missing: str) -> None:
    with pytest.raises(
        AuthError, match=r"^The Notion token cannot be revoked without the client ID and secret$"
    ):
        revoke_notion_token(make_notion_credentials(**{missing: None}), transport=fake_api({}, []))


def test_a_failed_revoke_names_the_status() -> None:
    transport = fake_api({"/v1/oauth/revoke": (400, {"error": "invalid_request"})}, [])

    with pytest.raises(AuthError, match=r"^Notion did not revoke the token: HTTP 400$"):
        revoke_notion_token(make_notion_credentials(), transport=transport)


def test_an_unreachable_revoke_endpoint_is_named() -> None:
    with pytest.raises(AuthError, match=r"^Could not reach Notion: connection refused$"):
        revoke_notion_token(make_notion_credentials(), transport=refusing_connections())


ISSUED = make_notion_credentials(access_token="new-access", refresh_token="new-refresh")
UNREVOKED = (
    "The token Notion just issued could not be saved, and revoking it failed too ({}), so remove the "
    "connection in Notion under Settings, Connections."
)


def revoke_answering(answer: int | None, seen: list[httpx2.Request]) -> httpx2.BaseTransport:
    if answer is None:
        return refusing_connections(seen)
    return fake_api({"/v1/oauth/revoke": (answer, {})}, seen)


def test_a_saved_sign_in_is_not_revoked(keychain: InMemoryKeyring) -> None:
    seen: list[httpx2.Request] = []

    save_or_revoke_notion(ISSUED, transport=revoke_answering(200, seen))

    assert (keychain.entries, seen) == (
        {
            ("skaldr", f"notion:{WORKSPACE_ID}"): ISSUED.model_dump_json(),
            ("skaldr", "index"): f'{{"jira": [], "notion": ["notion:{WORKSPACE_ID}"]}}',
        },
        [],
    )


@pytest.mark.parametrize(
    "failure",
    [OSError("disk full"), ValueError("bad entry"), KeyboardInterrupt(), EOFError()],
    ids=["an os error", "a value error", "an interrupt at a keychain prompt", "end of input at a prompt"],
)
def test_a_save_that_fails_with_any_other_exception_revokes_the_token_and_lets_it_through(
    failure: BaseException,
) -> None:
    keyring.set_keyring(WriteFailingKeyring(failure))
    seen: list[httpx2.Request] = []

    with pytest.raises(type(failure)) as raised:
        save_or_revoke_notion(ISSUED, transport=revoke_answering(200, seen))

    assert (raised.value, [summarise(request) for request in seen]) == (
        failure,
        [revoke_request_for("new-access")],
    )


@pytest.mark.parametrize(
    ("failure", "revoke_answer", "message", "cause"),
    [
        pytest.param(
            KeyringError("denied"),
            200,
            "The system keychain is unavailable: denied. The token Notion issued has been revoked.",
            (AuthError, "The system keychain is unavailable: denied"),
            id="revoked",
        ),
        pytest.param(
            KeyringError("denied."),
            200,
            "The system keychain is unavailable: denied. The token Notion issued has been revoked.",
            (AuthError, "The system keychain is unavailable: denied."),
            id="revoked after a message that ends in a period",
        ),
        pytest.param(
            KeyringError("denied"),
            400,
            "The system keychain is unavailable: denied. "
            + UNREVOKED.format("Notion did not revoke the token: HTTP 400"),
            (AuthError, "The system keychain is unavailable: denied"),
            id="the revoke answers 400",
        ),
        pytest.param(
            KeyringError("denied"),
            None,
            "The system keychain is unavailable: denied. "
            + UNREVOKED.format("Could not reach Notion: connection refused"),
            (AuthError, "The system keychain is unavailable: denied"),
            id="the revoke cannot reach notion",
        ),
        pytest.param(
            OSError("disk full"),
            None,
            "Saving to the keychain failed (OSError: disk full). "
            + UNREVOKED.format("Could not reach Notion: connection refused"),
            (OSError, "disk full"),
            id="an os error and an unreachable revoke",
        ),
        pytest.param(
            KeyboardInterrupt(),
            400,
            "Saving to the keychain failed (KeyboardInterrupt). "
            + UNREVOKED.format("Notion did not revoke the token: HTTP 400"),
            (KeyboardInterrupt, ""),
            id="an interrupt and a refused revoke",
        ),
    ],
)
def test_a_save_that_fails_says_whether_the_token_was_revoked(
    failure: BaseException, revoke_answer: int | None, message: str, cause: tuple[type, str]
) -> None:
    keyring.set_keyring(WriteFailingKeyring(failure))
    seen: list[httpx2.Request] = []

    with pytest.raises(AuthError) as raised:
        save_or_revoke_notion(ISSUED, transport=revoke_answering(revoke_answer, seen))

    error = raised.value
    assert (
        str(error),
        (type(error.__cause__), str(error.__cause__)),
        [summarise(request) for request in seen],
    ) == (
        message,
        cause,
        [revoke_request_for("new-access")],
    )
