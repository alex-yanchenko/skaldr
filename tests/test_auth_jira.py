import httpx2
import pytest

from skaldr.auth.jira import normalise_site, verify_jira_token
from skaldr.errors import AuthError
from tests.factories.auth_factory import basic, fake_api, make_jira_credentials, summarise

MYSELF = {"accountId": "account-id", "displayName": "Example Reader", "emailAddress": "reader@example.com"}


def test_a_valid_token_is_checked_against_myself_and_named() -> None:
    seen: list[httpx2.Request] = []

    credentials = verify_jira_token(
        "https://example.atlassian.net",
        "reader@example.com",
        "api-token",
        transport=fake_api({"/rest/api/3/myself": (200, MYSELF)}, seen),
    )

    assert credentials == make_jira_credentials()
    assert [summarise(request) for request in seen] == [
        {
            "method": "GET",
            "url": "https://example.atlassian.net/rest/api/3/myself",
            "authorization": basic("reader@example.com", "api-token"),
            "content_type": None,
            "body": None,
        }
    ]


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_token_is_refused(status: int) -> None:
    transport = fake_api({"/rest/api/3/myself": (status, {"errorMessages": []})}, [])

    with pytest.raises(AuthError, match=f"^Jira rejected the email and API token \\(HTTP {status}\\)"):
        verify_jira_token(
            "https://example.atlassian.net", "reader@example.com", "api-token", transport=transport
        )


def test_an_unexpected_status_is_named() -> None:
    transport = fake_api({"/rest/api/3/myself": (500, {})}, [])

    with pytest.raises(AuthError, match=r"^Jira answered HTTP 500 for /rest/api/3/myself$"):
        verify_jira_token(
            "https://example.atlassian.net", "reader@example.com", "api-token", transport=transport
        )


def test_a_myself_response_without_a_display_name_is_refused() -> None:
    transport = fake_api({"/rest/api/3/myself": (200, {"accountId": "account-id"})}, [])

    with pytest.raises(AuthError, match=r"^Jira's /rest/api/3/myself answer is not a user"):
        verify_jira_token(
            "https://example.atlassian.net", "reader@example.com", "api-token", transport=transport
        )


@pytest.mark.parametrize(
    ("typed", "site"),
    [
        ("example.atlassian.net", "https://example.atlassian.net"),
        ("https://example.atlassian.net/", "https://example.atlassian.net"),
        ("  https://example.atlassian.net/jira/your-work  ", "https://example.atlassian.net"),
    ],
)
def test_a_typed_site_becomes_its_https_origin(typed: str, site: str) -> None:
    assert normalise_site(typed) == site


@pytest.mark.parametrize("typed", ["http://example.atlassian.net", "", "https://"])
def test_a_site_that_is_not_an_https_host_is_refused(typed: str) -> None:
    with pytest.raises(AuthError, match=r"^The Jira site must be an https URL"):
        normalise_site(typed)
