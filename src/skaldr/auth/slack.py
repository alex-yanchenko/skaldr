from http import HTTPStatus
from typing import Final

import httpx2
from pydantic import BaseModel, ValidationError

from skaldr.auth import HTTP_TIMEOUT_SECONDS, CaughtWithoutChaining, printable_only
from skaldr.auth.store import SlackCredentials, is_slack_user_token, slack_token_refusal
from skaldr.errors import AuthError

SLACK_API: Final = "https://slack.com/api"
SLACK_APPS_PAGE: Final = "https://api.slack.com/apps"
SLACK_USER_SCOPES: Final = ("canvases:read", "canvases:write", "chat:write")
AUTH_TEST: Final = "auth.test"
REJECTED_SIGN_IN_ERRORS: Final = frozenset(
    {"invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive"}
)


class SlackIdentity(BaseModel):
    ok: bool
    error: str | None = None
    url: str | None = None
    team: str | None = None
    team_id: str | None = None
    user: str | None = None
    user_id: str | None = None


def signed_in_identity(access_token: str, *, transport: httpx2.BaseTransport | None = None) -> SlackIdentity:
    try:
        with httpx2.Client(transport=transport, timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{SLACK_API}/{AUTH_TEST}", headers={"Authorization": f"Bearer {access_token}"}
            )
    except httpx2.HTTPError as exc:
        raise AuthError(f"Could not reach Slack: {exc}") from exc
    if response.status_code != HTTPStatus.OK:
        raise AuthError(f"Slack answered HTTP {response.status_code} for {AUTH_TEST}")
    with CaughtWithoutChaining(ValidationError):
        identity = SlackIdentity.model_validate_json(response.content)
        if identity.ok:
            return identity
        raise AuthError(_refusal_message(identity.error))
    raise AuthError(f"Slack's {AUTH_TEST} answer is not a sign-in record")


def _refusal_message(error: str | None) -> str:
    code = printable_only(error or "no error named")
    if code in REJECTED_SIGN_IN_ERRORS:
        return (
            f"Slack rejected the user token ({code}). Copy the User OAuth Token again from your app at "
            f"{SLACK_APPS_PAGE}, under OAuth & Permissions"
        )
    return f"Slack refused {AUTH_TEST} ({code})"


def verify_slack_token(
    access_token: str, *, transport: httpx2.BaseTransport | None = None
) -> SlackCredentials:
    if not is_slack_user_token(access_token):
        raise AuthError(slack_token_refusal())
    identity = signed_in_identity(access_token, transport=transport)
    return SlackCredentials(
        access_token=access_token,
        team_id=identity.team_id,
        team_name=identity.team,
        user_id=identity.user_id,
        user_name=identity.user,
        url=identity.url,
    )
