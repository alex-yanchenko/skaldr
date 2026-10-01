import re
import socket
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from skaldr.auth.notion import revoke_notion_token, sign_in_to_notion
from skaldr.auth.store import NotionCredentials
from skaldr.errors import AuthError
from tests.factories.auth_factory import (
    TOKEN_RESPONSE,
    FakeBrowser,
    Visit,
    answerless,
    approving,
    basic_auth_header,
    fake_api,
    favicon,
    forged,
    forged_refusal,
    make_notion_credentials,
    refusing,
    refusing_connections,
    refusing_without_state,
    summarise,
)


def sign_in(
    browser: FakeBrowser,
    seen: list[httpx2.Request] | None = None,
    *,
    token: tuple[int, object] = (200, TOKEN_RESPONSE),
    transport: httpx2.BaseTransport | None = None,
    port: int = 0,
    timeout_seconds: float = 5,
) -> NotionCredentials:
    return sign_in_to_notion(
        "client-id",
        "client-secret",
        open_browser=browser,
        port=port,
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
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+/callback", browser.redirect_uri)
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
    "visit", [forged, answerless, forged_refusal], ids=["forged state", "no code or error", "forged refusal"]
)
def test_a_callback_that_does_not_answer_this_sign_in_never_reaches_the_token_endpoint(visit: Visit) -> None:
    seen: list[httpx2.Request] = []
    browser = FakeBrowser(visit)

    with pytest.raises(AuthError, match=r"^Timed out after 2 seconds waiting for Notion"):
        sign_in(browser, seen, timeout_seconds=2)

    assert (browser.finished(), seen) == ([400], [])


@pytest.mark.parametrize(
    "visit", [refusing, refusing_without_state], ids=["with the state", "without a state"]
)
def test_a_refused_consent_screen_stops_the_sign_in(visit: Visit) -> None:
    seen: list[httpx2.Request] = []
    browser = FakeBrowser(visit)

    with pytest.raises(AuthError, match=r"^Notion did not grant access: access_denied$"):
        sign_in(browser, seen)

    assert (browser.finished(), seen) == ([200], [])


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"error": "invalid_client"}, "Notion refused the sign-in: invalid_client"),
        (
            {"error": "invalid_grant", "error_description": "code expired"},
            "Notion refused the sign-in: invalid_grant (code expired)",
        ),
    ],
    ids=["error only", "error with a description"],
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
        ({"refresh_token": "secret-refresh-value"}, "access_token"),
        (["secret-refresh-value"], "(the whole answer)"),
    ],
    ids=["no access token", "not an object"],
)
def test_a_token_answer_with_bad_fields_names_them_and_not_the_tokens(answer: object, fields: str) -> None:
    with pytest.raises(AuthError) as raised:
        sign_in(FakeBrowser(approving), token=(200, answer))

    assert str(raised.value) == f"Notion's token answer is missing or has invalid fields: {fields}"


def test_a_token_answer_that_is_not_json_is_named() -> None:
    with pytest.raises(AuthError, match=r"^Notion's token answer is not JSON$"):
        sign_in(FakeBrowser(approving), token=(200, b"<html>maintenance</html>"))


def test_an_unreachable_token_endpoint_is_named() -> None:
    with pytest.raises(AuthError, match=r"^Could not reach Notion: connection refused$"):
        sign_in(FakeBrowser(approving), transport=refusing_connections())


def test_sign_in_times_out_when_the_browser_never_comes_back() -> None:
    with pytest.raises(AuthError, match=r"^Timed out after 0\.2 seconds .*; run `skaldr auth notion` again$"):
        sign_in(FakeBrowser(), timeout_seconds=0.2)


def test_a_busy_callback_port_is_named() -> None:
    with socket.create_server(("127.0.0.1", 0)) as blocker:
        port = blocker.getsockname()[1]

        with pytest.raises(AuthError, match=rf"^Cannot listen on 127\.0\.0\.1:{port} \(.+\); free the port"):
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
