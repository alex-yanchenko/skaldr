import json
import re

import httpx2
import keyring
import pytest
from keyring.errors import KeyringError

from skaldr.auth.notion import NotionSession, renewed_notion_credentials
from skaldr.auth.store import NotionCredentials, SignIn, load_notion
from skaldr.errors import AuthError
from tests.factories.auth_factory import (
    TOKEN_RESPONSE,
    InMemoryKeyring,
    WriteFailingKeyring,
    basic_auth_header,
    fake_api,
    make_notion_credentials,
    refusing_connections,
    rendered_traceback,
    seed_notion,
    summarise,
)

RENEWED = {**TOKEN_RESPONSE, "access_token": "renewed-access", "refresh_token": "renewed-refresh"}
RUN_AUTH_AGAIN = "; run `skaldr auth notion` again"


def _token_endpoint(answer: tuple[int, object], seen: list[httpx2.Request]) -> httpx2.MockTransport:
    return fake_api({"/v1/oauth/token": answer}, seen)


def test_renewing_sends_the_refresh_token_with_basic_auth_and_a_json_body() -> None:
    seen: list[httpx2.Request] = []

    renewed = renewed_notion_credentials(
        make_notion_credentials(), transport=_token_endpoint((200, RENEWED), seen)
    )

    assert renewed == make_notion_credentials(access_token="renewed-access", refresh_token="renewed-refresh")
    assert [summarise(request) for request in seen] == [
        {
            "method": "POST",
            "url": "https://api.notion.com/v1/oauth/token",
            "authorization": basic_auth_header("client-id", "client-secret"),
            "content_type": "application/json",
            "body": {"grant_type": "refresh_token", "refresh_token": "refresh-token"},
        }
    ]


def test_renewing_keeps_the_refresh_token_when_notion_issues_no_new_one() -> None:
    answer = {**RENEWED, "refresh_token": None}

    renewed = renewed_notion_credentials(
        make_notion_credentials(), transport=_token_endpoint((200, answer), [])
    )

    assert renewed == make_notion_credentials(access_token="renewed-access")


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        pytest.param(
            "refresh_token",
            "Notion refused the stored sign-in and it holds no refresh token" + RUN_AUTH_AGAIN,
            id="no-refresh-token",
        ),
        pytest.param(
            "client_secret",
            "Notion refused the stored sign-in and it cannot be renewed without the client ID and secret"
            + RUN_AUTH_AGAIN,
            id="no-client-secret",
        ),
    ],
)
def test_a_sign_in_without_what_renewing_needs_is_refused_without_a_request(
    missing: str, message: str
) -> None:
    seen: list[httpx2.Request] = []

    with pytest.raises(AuthError, match=f"^{re.escape(message)}$"):
        renewed_notion_credentials(
            make_notion_credentials(**{missing: None}), transport=_token_endpoint((200, RENEWED), seen)
        )
    assert seen == []


def test_a_refused_renewal_names_the_oauth_error_and_not_the_tokens() -> None:
    refused = (400, {"error": "invalid_grant", "error_description": "expired"})

    with pytest.raises(AuthError) as caught:
        renewed_notion_credentials(make_notion_credentials(), transport=_token_endpoint(refused, []))

    assert (str(caught.value), "refresh-token" in rendered_traceback(caught.value)) == (
        "Notion refused to renew the sign-in: invalid_grant (expired)" + RUN_AUTH_AGAIN,
        False,
    )


def test_an_unreachable_token_endpoint_is_named_when_renewing() -> None:
    with pytest.raises(AuthError, match=r"^Could not reach Notion: connection refused$"):
        renewed_notion_credentials(make_notion_credentials(), transport=refusing_connections())


def test_a_session_from_the_keychain_saves_the_renewed_sign_in_there() -> None:
    seed_notion(make_notion_credentials())
    stored = load_notion()
    assert stored is not None
    session = NotionSession(stored, transport=_token_endpoint((200, RENEWED), []))

    session.renew()

    renewed = make_notion_credentials(access_token="renewed-access", refresh_token="renewed-refresh")
    assert (session.access_token, load_notion()) == ("renewed-access", SignIn(renewed, "keychain"))


def test_a_session_from_the_environment_is_never_renewed_or_saved() -> None:
    seen: list[httpx2.Request] = []
    from_environment = SignIn(make_notion_credentials(refresh_token=None), "environment")
    session = NotionSession(from_environment, transport=_token_endpoint((200, RENEWED), seen))

    with pytest.raises(
        AuthError,
        match=r"^Notion refused NOTION_ACCESS_TOKEN; set a current token in NOTION_ACCESS_TOKEN$",
    ):
        session.renew()
    assert (seen, load_notion(), session.access_token) == ([], None, "access-token")


def _renewing_only(refresh_token: str, seen: list[str]) -> httpx2.MockTransport:
    def answer(request: httpx2.Request) -> httpx2.Response:
        sent = json.loads(request.content)["refresh_token"]
        seen.append(sent)
        if sent != refresh_token:
            return httpx2.Response(400, json={"error": "invalid_grant"})
        return httpx2.Response(200, json=RENEWED)

    return httpx2.MockTransport(answer)


def _stored() -> SignIn[NotionCredentials]:
    stored = load_notion()
    assert stored is not None
    return stored


def test_a_refused_renewal_is_tried_once_more_with_a_refresh_token_another_run_stored() -> None:
    seed_notion(make_notion_credentials())
    session = NotionSession(_stored(), transport=_renewing_only("rotated-refresh", sent := []))
    seed_notion(make_notion_credentials(refresh_token="rotated-refresh"))

    session.renew()

    renewed = make_notion_credentials(access_token="renewed-access", refresh_token="renewed-refresh")
    assert (sent, session.access_token, load_notion()) == (
        ["refresh-token", "rotated-refresh"],
        "renewed-access",
        SignIn(renewed, "keychain"),
    )


def test_a_refused_renewal_with_no_other_stored_refresh_token_says_to_sign_in_again() -> None:
    seed_notion(make_notion_credentials())
    session = NotionSession(_stored(), transport=_renewing_only("rotated-refresh", sent := []))

    with pytest.raises(
        AuthError, match=re.escape(f"Notion refused to renew the sign-in: invalid_grant{RUN_AUTH_AGAIN}")
    ):
        session.renew()
    assert sent == ["refresh-token"]


def test_a_renewed_token_is_used_even_when_the_keychain_refuses_to_save_it(keychain: InMemoryKeyring) -> None:
    seed_notion(make_notion_credentials())
    session = NotionSession(_stored(), transport=_token_endpoint((200, RENEWED), []))
    failing = WriteFailingKeyring(KeyringError("locked"))
    failing.entries = dict(keychain.entries)
    keyring.set_keyring(failing)

    with pytest.raises(AuthError, match=r"^The system keychain is unavailable: locked$"):
        session.renew()
    assert session.access_token == "renewed-access"


def test_a_sign_in_that_could_not_be_saved_after_renewal_is_not_renewed() -> None:
    seen: list[httpx2.Request] = []
    unidentified = SignIn(make_notion_credentials(workspace_id=None), "keychain")
    session = NotionSession(unidentified, transport=_token_endpoint((200, RENEWED), seen))

    with pytest.raises(
        AuthError,
        match=re.escape(
            "Notion refused the stored sign-in, which has no workspace id, so a renewed token could not be "
            f"saved{RUN_AUTH_AGAIN}"
        ),
    ):
        session.renew()
    assert seen == []


def test_a_session_first_takes_a_newer_token_another_run_stored_without_asking_notion() -> None:
    seed_notion(make_notion_credentials())
    seen: list[httpx2.Request] = []
    session = NotionSession(_stored(), transport=_token_endpoint((200, RENEWED), seen))
    seed_notion(make_notion_credentials(access_token="other-access", refresh_token="other-refresh"))

    session.renew()

    assert (session.access_token, seen) == ("other-access", [])


def test_a_stored_token_that_is_refused_too_is_renewed_with_its_refresh_token() -> None:
    seed_notion(make_notion_credentials())
    session = NotionSession(_stored(), transport=_renewing_only("other-refresh", sent := []))
    seed_notion(make_notion_credentials(access_token="other-access", refresh_token="other-refresh"))

    session.renew()
    session.renew()

    assert (sent, session.access_token) == (["other-refresh"], "renewed-access")


def test_a_session_renews_with_notion_only_once() -> None:
    seed_notion(make_notion_credentials())
    session = NotionSession(_stored(), transport=_token_endpoint((200, RENEWED), seen := []))
    session.renew()

    with pytest.raises(AuthError, match=re.escape(f"Notion refused the renewed sign-in{RUN_AUTH_AGAIN}")):
        session.renew()
    assert len(seen) == 1
