import httpx2
import pytest

from skaldr.auth.jira import verify_jira_token
from skaldr.auth.store import JiraCredentials
from skaldr.errors import AuthError
from tests.factories.auth_factory import (
    MYSELF,
    basic_auth_header,
    fake_api,
    make_jira_credentials,
    refusing_connections,
    summarise,
)


def verify(transport: httpx2.BaseTransport) -> JiraCredentials:
    return verify_jira_token(
        "https://example.atlassian.net", "reader@example.com", "api-token", transport=transport
    )


def test_a_valid_token_is_checked_against_myself_and_named() -> None:
    seen: list[httpx2.Request] = []

    credentials = verify(fake_api({"/rest/api/3/myself": (200, MYSELF)}, seen))

    assert credentials == make_jira_credentials()
    assert [summarise(request) for request in seen] == [
        {
            "method": "GET",
            "url": "https://example.atlassian.net/rest/api/3/myself",
            "authorization": basic_auth_header("reader@example.com", "api-token"),
            "content_type": None,
            "body": None,
        }
    ]


@pytest.mark.parametrize("status", [401, 403], ids=["unauthorized", "forbidden"])
def test_a_rejected_token_is_refused(status: int) -> None:
    with pytest.raises(AuthError, match=rf"^Jira rejected the email and API token \(HTTP {status}\)"):
        verify(fake_api({"/rest/api/3/myself": (status, {"errorMessages": []})}, []))


def test_an_unexpected_status_is_named() -> None:
    with pytest.raises(AuthError, match=r"^Jira answered HTTP 500 for /rest/api/3/myself$"):
        verify(fake_api({"/rest/api/3/myself": (500, {})}, []))


@pytest.mark.parametrize(
    "body", [{"accountId": "account-id"}, b"<html>login</html>"], ids=["no display name", "not json"]
)
def test_a_myself_answer_that_is_not_a_user_is_refused(body: object) -> None:
    with pytest.raises(AuthError, match=r"^Jira's /rest/api/3/myself answer is not a user record$"):
        verify(fake_api({"/rest/api/3/myself": (200, body)}, []))


def test_an_unreachable_site_is_named() -> None:
    with pytest.raises(
        AuthError, match=r"^Could not reach Jira at https://example\.atlassian\.net: connection refused$"
    ):
        verify(refusing_connections())
