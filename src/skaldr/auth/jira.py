from urllib.parse import urlsplit

import httpx2
from pydantic import BaseModel, Field, ValidationError

from skaldr.auth.store import JiraCredentials
from skaldr.errors import AuthError

API_TOKENS_PAGE = "https://id.atlassian.com/manage-profile/security/api-tokens"
MYSELF_PATH = "/rest/api/3/myself"
HTTP_TIMEOUT_SECONDS = 30.0


class _JiraUser(BaseModel):
    display_name: str = Field(alias="displayName")


def normalise_site(typed: str) -> str:
    text = typed.strip()
    url = urlsplit(text if "://" in text else f"https://{text}")
    if url.scheme != "https" or not url.hostname:
        raise AuthError(
            f"The Jira site must be an https URL like https://<site>.atlassian.net, not {typed!r}"
        )
    return f"https://{url.hostname}" + (f":{url.port}" if url.port else "")


def verify_jira_token(
    site: str, email: str, api_token: str, *, transport: httpx2.BaseTransport | None = None
) -> JiraCredentials:
    try:
        with httpx2.Client(transport=transport, timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.get(
                f"{site}{MYSELF_PATH}", auth=(email, api_token), headers={"Accept": "application/json"}
            )
    except httpx2.HTTPError as exc:
        raise AuthError(f"Could not reach Jira at {site}: {exc}") from exc
    if response.status_code in (401, 403):
        raise AuthError(
            f"Jira rejected the email and API token (HTTP {response.status_code}). Check both, or create "
            f"a new token at {API_TOKENS_PAGE}"
        )
    if response.status_code != 200:
        raise AuthError(f"Jira answered HTTP {response.status_code} for {MYSELF_PATH}")
    try:
        user = _JiraUser.model_validate_json(response.content)
    except ValidationError as exc:
        raise AuthError(f"Jira's {MYSELF_PATH} answer is not a user: {exc}") from exc
    return JiraCredentials(site=site, email=email, api_token=api_token, display_name=user.display_name)
