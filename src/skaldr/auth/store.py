import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import BaseModel, ConfigDict, HttpUrl, ValidationError, field_validator
from pydantic_core import PydanticCustomError

from skaldr.errors import AuthError

KEYCHAIN_SERVICE = "skaldr"

Service = Literal["notion", "jira"]
Source = Literal["keychain", "environment"]

NOTION_ENVIRONMENT = ("NOTION_ACCESS_TOKEN", "NOTION_CLIENT_ID", "NOTION_CLIENT_SECRET")
JIRA_ENVIRONMENT = ("JIRA_SITE", "JIRA_EMAIL", "JIRA_API_TOKEN")
_JIRA_CLOUD_HOST_SUFFIX = ".atlassian.net"


class UnreadableEntryError(AuthError):
    pass


class NotionCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_id: str | None
    client_secret: str | None
    access_token: str
    refresh_token: str | None
    workspace_name: str | None


class JiraCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    email: str
    api_token: str
    display_name: str | None

    @field_validator("site")
    @classmethod
    def _site_is_an_https_origin(cls, site: str) -> str:
        origin = _https_origin(site)
        if origin is None:
            raise PydanticCustomError("https_origin", "{refusal}", {"refusal": _site_refusal(site)})
        return origin


CredentialsT = TypeVar("CredentialsT", NotionCredentials, JiraCredentials)


@dataclass(frozen=True)
class SignIn(Generic[CredentialsT]):
    credentials: CredentialsT
    source: Source


def normalise_site(typed: str) -> str:
    origin = _https_origin(typed)
    if origin is None:
        raise AuthError(_site_refusal(typed))
    return origin


def jira_credentials(
    site: str, email: str, api_token: str, display_name: str | None = None
) -> JiraCredentials:
    try:
        return JiraCredentials(site=site, email=email, api_token=api_token, display_name=display_name)
    except ValidationError as exc:
        raise AuthError(exc.errors(include_input=False)[0]["msg"]) from exc


def save_notion(credentials: NotionCredentials) -> None:
    _save("notion", credentials)


def save_jira(credentials: JiraCredentials) -> None:
    _save("jira", credentials)


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


def notion_client_from_environment() -> tuple[str | None, str | None]:
    _, client_id, client_secret = map(_environment, NOTION_ENVIRONMENT)
    return client_id, client_secret


def forget(service: Service) -> bool:
    with _keychain_errors_as_auth_errors():
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, service)
        except PasswordDeleteError:
            return False
    return True


def _https_origin(typed: str) -> str | None:
    text = typed.strip()
    if "\\" in text:
        return None
    try:
        url = HttpUrl(text if "://" in text else f"https://{text}")
    except ValidationError:
        return None
    if url.scheme != "https" or not _is_a_jira_cloud_host(url.host):
        return None
    if _carries_more_than_a_path(url):
        return None
    return f"https://{url.host}" + ("" if url.port in (None, 443) else f":{url.port}")


def _is_a_jira_cloud_host(host: str | None) -> bool:
    return host is not None and host.endswith(_JIRA_CLOUD_HOST_SUFFIX)


def _carries_more_than_a_path(url: HttpUrl) -> bool:
    parts = (url.username, url.password, url.query, url.fragment)
    return any(part is not None for part in parts)


def _site_refusal(typed: str) -> str:
    return f"The Jira site must be an https URL like https://<site>.atlassian.net, not {typed!r}"


@contextmanager
def _keychain_errors_as_auth_errors() -> Generator[None, None, None]:
    try:
        yield
    except KeyringError as exc:
        raise AuthError(f"The system keychain is unavailable: {exc}") from exc


def _save(service: Service, credentials: BaseModel) -> None:
    with _keychain_errors_as_auth_errors():
        keyring.set_password(KEYCHAIN_SERVICE, service, credentials.model_dump_json())


def _load_from_keychain(service: Service, model: type[CredentialsT]) -> CredentialsT | None:
    with _keychain_errors_as_auth_errors():
        stored = keyring.get_password(KEYCHAIN_SERVICE, service)
    if stored is None:
        return None
    try:
        return model.model_validate_json(stored)
    except ValidationError as exc:
        raise UnreadableEntryError(
            f"The keychain entry for {service} is unreadable; run `skaldr auth {service}` again"
        ) from exc


def _environment(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def _notion_from_environment() -> NotionCredentials | None:
    access_token, client_id, client_secret = map(_environment, NOTION_ENVIRONMENT)
    if access_token is None:
        return None
    return NotionCredentials(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        refresh_token=None,
        workspace_name=None,
    )


def _jira_from_environment() -> JiraCredentials | None:
    values = [_environment(name) for name in JIRA_ENVIRONMENT]
    missing = [name for name, value in zip(JIRA_ENVIRONMENT, values, strict=True) if value is None]
    if len(missing) == len(JIRA_ENVIRONMENT):
        return None
    site, email, api_token = values
    if site is None or email is None or api_token is None:
        raise AuthError(f"{', '.join(JIRA_ENVIRONMENT)} go together; missing {', '.join(missing)}")
    try:
        return jira_credentials(site, email, api_token)
    except AuthError as exc:
        raise AuthError(f"JIRA_SITE: {exc}") from exc
