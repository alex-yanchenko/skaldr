import os
import sys
import threading
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar, cast

import keyring
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import BaseModel, ConfigDict, HttpUrl, ValidationError, field_validator
from pydantic_core import PydanticCustomError

from skaldr.auth import CaughtWithoutChaining
from skaldr.errors import AuthError

KEYCHAIN_SERVICE = "skaldr"
KEYCHAIN_NOTICE_SECONDS = 2.0
KEYCHAIN_TIMEOUT_SECONDS = 120.0
KEYCHAIN_WAIT_NOTICE = (
    "Waiting for the system keychain; if it is locked or shows a prompt for skaldr, "
    "unlock it or answer there."
)
Answer = TypeVar("Answer")

Service = Literal["notion", "jira"]
Source = Literal["keychain", "environment"]

_NOTION_ACCESS_TOKEN = "NOTION_ACCESS_TOKEN"
_NOTION_CLIENT_ID = "NOTION_CLIENT_ID"
_NOTION_CLIENT_SECRET = "NOTION_CLIENT_SECRET"
_NOTION_CLIENT_ENVIRONMENT = (_NOTION_CLIENT_ID, _NOTION_CLIENT_SECRET)
NOTION_ENVIRONMENT = (_NOTION_ACCESS_TOKEN, *_NOTION_CLIENT_ENVIRONMENT)
_JIRA_SITE = "JIRA_SITE"
_JIRA_EMAIL = "JIRA_EMAIL"
_JIRA_API_TOKEN = "JIRA_API_TOKEN"
JIRA_ENVIRONMENT = (_JIRA_SITE, _JIRA_EMAIL, _JIRA_API_TOKEN)
_JIRA_CLOUD_HOST_SUFFIX = ".atlassian.net"
_INSECURE_KEYRING_MODULES = ("keyrings.alt", "keyring.backends.null", "keyring.backends.fail")
_SITE_REQUIREMENT = "The Jira site must be an https URL like https://<site>.atlassian.net"


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
    with CaughtWithoutChaining(ValidationError) as invalid:
        return JiraCredentials(site=site, email=email, api_token=api_token, display_name=display_name)
    raise AuthError(invalid.error.errors(include_input=False)[0]["msg"])


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
    return _environment(_NOTION_CLIENT_ID), _environment(_NOTION_CLIENT_SECRET)


def forget(service: Service) -> bool:
    with _keychain_errors_as_auth_errors():
        try:
            _from_the_keychain(lambda: keyring.delete_password(KEYCHAIN_SERVICE, service))
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
    if _carries_userinfo_query_or_fragment(url):
        return None
    return f"https://{url.host}" + ("" if url.port in (None, 443) else f":{url.port}")


def _is_a_jira_cloud_host(host: str | None) -> bool:
    return host is not None and host.endswith(_JIRA_CLOUD_HOST_SUFFIX)


def _carries_userinfo_query_or_fragment(url: HttpUrl) -> bool:
    parts = (url.username, url.password, url.query, url.fragment)
    return any(part is not None for part in parts)


def _site_refusal(typed: str) -> str:
    if "@" in typed:
        return f"{_SITE_REQUIREMENT}, with no user name or password before the host"
    return f"{_SITE_REQUIREMENT}, not {typed!r}"


@dataclass
class _KeychainReply(Generic[Answer]):
    value: Answer | None = None
    error: BaseException | None = None


def _from_the_keychain(ask: Callable[[], Answer]) -> Answer:
    answered = threading.Event()
    reply: _KeychainReply[Answer] = _KeychainReply()

    def ask_and_record() -> None:
        try:
            reply.value = ask()
        except BaseException as exc:
            reply.error = exc
        finally:
            answered.set()

    threading.Thread(target=ask_and_record, name="skaldr-keychain", daemon=True).start()
    if not answered.wait(KEYCHAIN_NOTICE_SECONDS):
        print(KEYCHAIN_WAIT_NOTICE, file=sys.stderr)
        if not answered.wait(KEYCHAIN_TIMEOUT_SECONDS - KEYCHAIN_NOTICE_SECONDS):
            raise AuthError(
                f"The system keychain did not answer within {KEYCHAIN_TIMEOUT_SECONDS:g} seconds; "
                "unlock it or answer its prompt, then run the command again. A change skaldr asked for "
                "may still be applied if the keychain answers later"
            )
    if reply.error is not None:
        raise reply.error
    return cast("Answer", reply.value)


@contextmanager
def _keychain_errors_as_auth_errors() -> Generator[None, None, None]:
    try:
        yield
    except KeyringError as exc:
        raise AuthError(f"The system keychain is unavailable: {exc}") from exc


def refuse_an_unusable_keychain(service: Service) -> None:
    _refuse_an_insecure_keyring()
    with _keychain_errors_as_auth_errors():
        _from_the_keychain(lambda: keyring.get_password(KEYCHAIN_SERVICE, service))


def _save(service: Service, credentials: BaseModel) -> None:
    _refuse_an_insecure_keyring()
    serialized = credentials.model_dump_json()
    with _keychain_errors_as_auth_errors():
        _from_the_keychain(lambda: keyring.set_password(KEYCHAIN_SERVICE, service, serialized))


def _refuse_an_insecure_keyring() -> None:
    with _keychain_errors_as_auth_errors():
        backend = _from_the_keychain(keyring.get_keyring)
    candidates: list[KeyringBackend] = backend.backends if isinstance(backend, ChainerBackend) else [backend]
    for candidate in candidates:
        insecure_base = _insecure_keyring_base(type(candidate))
        if insecure_base is not None:
            name = _backend_name(type(candidate), insecure_base)
            raise AuthError(
                f"skaldr will not save to the keyring backend {name}: the keyrings.alt backends store "
                "secrets where skaldr cannot vouch for them, and the null and fail backends store nothing. "
                "Choose a secure backend with the PYTHON_KEYRING_BACKEND environment variable or keyring's "
                "keyringrc.cfg, for example keyring.backends.macOS.Keyring, "
                "keyring.backends.Windows.WinVaultKeyring or keyring.backends.SecretService.Keyring"
            )


def _insecure_keyring_base(backend_class: type) -> type | None:
    return next(
        (base for base in backend_class.__mro__ if _is_an_insecure_keyring_module(base.__module__)), None
    )


def _backend_name(backend_class: type, insecure_base: type) -> str:
    name = _class_path(backend_class)
    return name if backend_class is insecure_base else f"{name} (a {_class_path(insecure_base)})"


def _class_path(backend_class: type) -> str:
    return f"{backend_class.__module__}.{backend_class.__qualname__}"


def _is_an_insecure_keyring_module(module: str) -> bool:
    return any(
        module == insecure or module.startswith(f"{insecure}.") for insecure in _INSECURE_KEYRING_MODULES
    )


def _load_from_keychain(service: Service, model: type[CredentialsT]) -> CredentialsT | None:
    with _keychain_errors_as_auth_errors():
        stored = _from_the_keychain(lambda: keyring.get_password(KEYCHAIN_SERVICE, service))
    if stored is None:
        return None
    with CaughtWithoutChaining(ValidationError):
        return model.model_validate_json(stored)
    raise UnreadableEntryError(
        f"The keychain entry for {service} is unreadable; run `skaldr auth {service}` again"
    )


def _environment(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def _all_or_none_from_environment(names: Sequence[str]) -> Mapping[str, str] | None:
    present = {name: value for name in names if (value := _environment(name)) is not None}
    if not present:
        return None
    missing = [name for name in names if name not in present]
    if missing:
        raise AuthError(f"{', '.join(names)} go together; missing {', '.join(missing)}")
    return present


def _notion_from_environment() -> NotionCredentials | None:
    access_token = _environment(_NOTION_ACCESS_TOKEN)
    if access_token is None:
        return None
    client = _all_or_none_from_environment(_NOTION_CLIENT_ENVIRONMENT) or {}
    return NotionCredentials(
        client_id=client.get(_NOTION_CLIENT_ID),
        client_secret=client.get(_NOTION_CLIENT_SECRET),
        access_token=access_token,
        refresh_token=None,
        workspace_name=None,
    )


def _jira_from_environment() -> JiraCredentials | None:
    values = _all_or_none_from_environment(JIRA_ENVIRONMENT)
    if values is None:
        return None
    with CaughtWithoutChaining(AuthError) as refused:
        return jira_credentials(values[_JIRA_SITE], values[_JIRA_EMAIL], values[_JIRA_API_TOKEN])
    raise AuthError(f"{_JIRA_SITE}: {refused.error}")
