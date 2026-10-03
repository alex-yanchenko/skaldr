from http import HTTPStatus

import httpx2
from pydantic import BaseModel, Field, ValidationError

from skaldr.auth import HTTP_TIMEOUT_SECONDS, caught_without_chaining
from skaldr.auth.store import JiraCredentials, jira_credentials
from skaldr.errors import AuthError

API_TOKENS_PAGE = "https://id.atlassian.com/manage-profile/security/api-tokens"
_MYSELF_PATH = "/rest/api/3/myself"


class _JiraUser(BaseModel):
    display_name: str = Field(alias="displayName")


def verify_jira_token(
    site: str, email: str, api_token: str, *, transport: httpx2.BaseTransport | None = None
) -> JiraCredentials:
    unverified = jira_credentials(site, email, api_token)
    try:
        with httpx2.Client(transport=transport, timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.get(
                f"{unverified.site}{_MYSELF_PATH}",
                auth=(unverified.email, unverified.api_token),
                headers={"Accept": "application/json"},
            )
    except httpx2.HTTPError as exc:
        raise AuthError(f"Could not reach Jira at {unverified.site}: {exc}") from exc
    if response.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        raise AuthError(
            f"Jira rejected the email and API token (HTTP {response.status_code}). Check both, or create "
            f"a new token at {API_TOKENS_PAGE}"
        )
    if response.status_code != HTTPStatus.OK:
        raise AuthError(f"Jira answered HTTP {response.status_code} for {_MYSELF_PATH}")
    with caught_without_chaining(ValidationError):
        user = _JiraUser.model_validate_json(response.content)
        return unverified.model_copy(update={"display_name": user.display_name})
    raise AuthError(f"Jira's {_MYSELF_PATH} answer is not a user record")
