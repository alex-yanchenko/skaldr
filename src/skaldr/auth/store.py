import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import BaseModel, ConfigDict, ValidationError

from skaldr.errors import AuthError

KEYCHAIN_SERVICE = "skaldr"

Service = Literal["notion", "jira"]
Source = Literal["keychain", "environment"]

JIRA_ENVIRONMENT = ("JIRA_SITE", "JIRA_EMAIL", "JIRA_API_TOKEN")


class NotionCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_id: str | None
    client_secret: str | None
    access_token: str
    refresh_token: str | None
    workspace_name: str | None
    bot_id: str | None


class JiraCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    email: str
    api_token: str
    display_name: str | None


Credentials = TypeVar("Credentials", NotionCredentials, JiraCredentials)


@dataclass(frozen=True)
class SignIn(Generic[Credentials]):
    credentials: Credentials
    source: Source


def save_notion(credentials: NotionCredentials) -> None:
    with _keychain_errors_as_auth_errors():
        keyring.set_password(KEYCHAIN_SERVICE, "notion", credentials.model_dump_json())


def save_jira(credentials: JiraCredentials) -> None:
    with _keychain_errors_as_auth_errors():
        keyring.set_password(KEYCHAIN_SERVICE, "jira", credentials.model_dump_json())


def load_notion() -> SignIn[NotionCredentials] | None:
    from_environment = _notion_from_environment()
    if from_environment is not None:
        return SignIn(from_environment, "environment")
    stored = stored_notion()
    return None if stored is None else SignIn(stored, "keychain")


def load_jira() -> SignIn[JiraCredentials] | None:
    from_environment = _jira_from_environment()
    if from_environment is not None:
        return SignIn(from_environment, "environment")
    stored = _load_from_keychain("jira", JiraCredentials)
    return None if stored is None else SignIn(stored, "keychain")


def stored_notion() -> NotionCredentials | None:
    return _load_from_keychain("notion", NotionCredentials)


def forget(service: Service) -> bool:
    with _keychain_errors_as_auth_errors():
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, service)
        except PasswordDeleteError:
            return False
    return True


@contextmanager
def _keychain_errors_as_auth_errors() -> Generator[None, None, None]:
    try:
        yield
    except KeyringError as exc:
        raise AuthError(f"The system keychain is unavailable: {exc}") from exc


def _load_from_keychain(service: Service, model: type[Credentials]) -> Credentials | None:
    with _keychain_errors_as_auth_errors():
        stored = keyring.get_password(KEYCHAIN_SERVICE, service)
    if stored is None:
        return None
    try:
        return model.model_validate_json(stored)
    except ValidationError as exc:
        raise AuthError(
            f"The keychain entry for {service} is unreadable; run `skaldr auth {service}` again"
        ) from exc


def _notion_from_environment() -> NotionCredentials | None:
    access_token = os.environ.get("NOTION_ACCESS_TOKEN")
    if not access_token:
        return None
    return NotionCredentials(
        client_id=os.environ.get("NOTION_CLIENT_ID") or None,
        client_secret=os.environ.get("NOTION_CLIENT_SECRET") or None,
        access_token=access_token,
        refresh_token=os.environ.get("NOTION_REFRESH_TOKEN") or None,
        workspace_name=None,
        bot_id=None,
    )


def _jira_from_environment() -> JiraCredentials | None:
    site, email, api_token = (os.environ.get(name, "") for name in JIRA_ENVIRONMENT)
    if not (site or email or api_token):
        return None
    missing = [
        name for name, value in zip(JIRA_ENVIRONMENT, (site, email, api_token), strict=True) if not value
    ]
    if missing:
        raise AuthError(f"{', '.join(JIRA_ENVIRONMENT)} go together; missing {', '.join(missing)}")
    return JiraCredentials(site=site, email=email, api_token=api_token, display_name=None)
