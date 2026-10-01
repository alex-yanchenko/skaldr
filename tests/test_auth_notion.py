import socket
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from skaldr.auth.notion import refresh_notion_token, revoke_notion_token, sign_in_to_notion
from skaldr.auth.store import NotionCredentials
from skaldr.errors import AuthError
from tests.factories.auth_factory import (
    TOKEN_RESPONSE,
    FakeBrowser,
    approving,
    basic,
    fake_api,
    make_notion_credentials,
    summarise,
)


def sign_in(
    browser: FakeBrowser, seen: list[httpx2.Request], **routes: tuple[int, object]
) -> NotionCredentials:
    return sign_in_to_notion(
        "client-id",
        "client-secret",
        open_browser=browser,
        port=0,
        transport=fake_api({"/v1/oauth/token": routes.get("token", (200, TOKEN_RESPONSE))}, seen),
        timeout_seconds=5,
    )


def test_sign_in_exchanges_the_code_with_basic_auth_and_a_json_body() -> None:
    seen: list[httpx2.Request] = []
    browser = FakeBrowser(approving)

    credentials = sign_in(browser, seen)

    assert credentials == make_notion_credentials(access_token="new-access", refresh_token="new-refresh")
    authorize = urlsplit(browser.opened[0])
    assert (authorize.scheme, authorize.netloc, authorize.path) == (
        "https",
        "api.notion.com",
        "/v1/oauth/authorize",
    )
    query = parse_qs(authorize.query)
    assert query == {
        "response_type": ["code"],
        "client_id": ["client-id"],
        "redirect_uri": [browser.redirect_uri],
        "state": query["state"],
        "owner": ["user"],
    }
    assert urlsplit(browser.redirect_uri).hostname == "localhost"
    assert urlsplit(browser.redirect_uri).path == "/callback"
    assert [summarise(request) for request in seen] == [
        {
            "method": "POST",
            "url": "https://api.notion.com/v1/oauth/token",
            "authorization": basic("client-id", "client-secret"),
            "content_type": "application/json",
            "body": {
                "grant_type": "authorization_code",
                "code": "the-code",
                "redirect_uri": browser.redirect_uri,
            },
        }
    ]


def test_a_callback_with_a_forged_state_never_reaches_the_token_endpoint() -> None:
    seen: list[httpx2.Request] = []

    with pytest.raises(AuthError, match="mismatching_state"):
        sign_in(FakeBrowser(lambda _state: "code=the-code&state=forged"), seen)

    assert seen == []


def test_a_refused_consent_screen_stops_the_sign_in() -> None:
    seen: list[httpx2.Request] = []

    with pytest.raises(AuthError, match=r"^Notion did not grant access: access_denied$"):
        sign_in(FakeBrowser(lambda state: f"error=access_denied&state={state}"), seen)

    assert seen == []


def test_a_rejected_client_secret_names_the_oauth_error() -> None:
    with pytest.raises(AuthError, match="invalid_client"):
        sign_in(FakeBrowser(approving), [], token=(401, {"error": "invalid_client"}))


def test_sign_in_times_out_when_the_browser_never_comes_back() -> None:
    with pytest.raises(AuthError, match=r"^Timed out waiting for Notion to redirect back"):
        sign_in_to_notion(
            "client-id",
            "client-secret",
            open_browser=FakeBrowser(None),
            port=0,
            transport=fake_api({}, []),
            timeout_seconds=0.2,
        )


def test_a_busy_callback_port_is_named() -> None:
    with socket.create_server(("127.0.0.1", 0)) as blocker:
        port = blocker.getsockname()[1]
        with pytest.raises(AuthError, match=f"^Port {port} is in use; free it or pass --port"):
            sign_in_to_notion(
                "client-id",
                "client-secret",
                open_browser=FakeBrowser(None),
                port=port,
                transport=fake_api({}, []),
                timeout_seconds=0.2,
            )


def test_refresh_sends_the_refresh_grant_and_stores_the_rotated_pair() -> None:
    seen: list[httpx2.Request] = []
    transport = fake_api({"/v1/oauth/token": (200, TOKEN_RESPONSE)}, seen)

    refreshed = refresh_notion_token(make_notion_credentials(), transport=transport)

    assert refreshed == make_notion_credentials(access_token="new-access", refresh_token="new-refresh")
    assert [summarise(request) for request in seen] == [
        {
            "method": "POST",
            "url": "https://api.notion.com/v1/oauth/token",
            "authorization": basic("client-id", "client-secret"),
            "content_type": "application/json",
            "body": {"grant_type": "refresh_token", "refresh_token": "refresh-token"},
        }
    ]


def test_refresh_keeps_the_refresh_token_when_notion_does_not_rotate_it() -> None:
    response = {key: value for key, value in TOKEN_RESPONSE.items() if key != "refresh_token"}
    transport = fake_api({"/v1/oauth/token": (200, response)}, [])

    refreshed = refresh_notion_token(make_notion_credentials(), transport=transport)

    assert refreshed == make_notion_credentials(access_token="new-access")


@pytest.mark.parametrize(
    "missing", [{"refresh_token": None}, {"client_id": None}, {"client_secret": None}], ids=str
)
def test_refresh_without_a_refresh_token_or_client_says_to_sign_in_again(missing: dict[str, None]) -> None:
    with pytest.raises(
        AuthError, match=r"^The Notion token cannot be refreshed; run `skaldr auth notion` again$"
    ):
        refresh_notion_token(make_notion_credentials(**missing), transport=fake_api({}, []))


def test_revoke_sends_the_access_token_with_basic_auth() -> None:
    seen: list[httpx2.Request] = []

    revoke_notion_token(make_notion_credentials(), transport=fake_api({"/v1/oauth/revoke": (200, {})}, seen))

    assert [summarise(request) for request in seen] == [
        {
            "method": "POST",
            "url": "https://api.notion.com/v1/oauth/revoke",
            "authorization": basic("client-id", "client-secret"),
            "content_type": "application/json",
            "body": {"token": "access-token"},
        }
    ]


def test_a_token_from_the_environment_without_a_client_cannot_be_revoked() -> None:
    with pytest.raises(
        AuthError, match=r"^The Notion token cannot be revoked without the client ID and secret$"
    ):
        revoke_notion_token(make_notion_credentials(client_id=None), transport=fake_api({}, []))


def test_a_failed_revoke_names_the_status() -> None:
    transport = fake_api({"/v1/oauth/revoke": (400, {"error": "invalid_request"})}, [])

    with pytest.raises(AuthError, match=r"^Notion did not revoke the token: HTTP 400$"):
        revoke_notion_token(make_notion_credentials(), transport=transport)
