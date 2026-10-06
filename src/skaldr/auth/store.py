import json
import os
import sys
import threading
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar, cast

import keyring
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import BaseModel, ConfigDict, HttpUrl, TypeAdapter, ValidationError, field_validator
from pydantic_core import PydanticCustomError

from skaldr.auth import CaughtWithoutChaining, printable_only
from skaldr.errors import AuthError

KEYCHAIN_SERVICE = "skaldr"
KEYCHAIN_INDEX_USERNAME = "index"
_UNIDENTIFIED_WORKSPACE = "unidentified"
_UNREADABLE_LEGACY_ENTRY = "an unreadable entry"
_INDEX_SHAPE = TypeAdapter(dict[str, list[str]])
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
    workspace_id: str | None = None
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


@dataclass(frozen=True)
class _Kind(Generic[CredentialsT]):
    service: Service
    model: type[CredentialsT]
    identify: Callable[[CredentialsT], str]


_JIRA = _Kind[JiraCredentials]("jira", JiraCredentials, lambda credentials: credentials.site)
_NOTION = _Kind[NotionCredentials](
    "notion",
    NotionCredentials,
    lambda credentials: credentials.workspace_id or _UNIDENTIFIED_WORKSPACE,
)


@dataclass(frozen=True)
class StoredEntry(Generic[CredentialsT]):
    service: Service
    username: str
    credentials: CredentialsT | None

    @property
    def identifier(self) -> str | None:
        prefix = f"{self.service}:"
        return self.username.removeprefix(prefix) if self.username.startswith(prefix) else None

    @property
    def unreadable_message(self) -> str:
        label = self.service if self.identifier is None else f"{self.service} {self.identifier}"
        return f"The keychain entry for {label} is unreadable; run `skaldr auth {self.service}` again"


def save_notion(credentials: NotionCredentials) -> None:
    _save(_NOTION, credentials)


def save_jira(credentials: JiraCredentials) -> None:
    _save(_JIRA, credentials)


def stored_jira_sign_ins() -> list[StoredEntry[JiraCredentials]]:
    return _in_the_keychain(lambda: _entries(_JIRA))


def stored_notion_sign_ins() -> list[StoredEntry[NotionCredentials]]:
    return _in_the_keychain(lambda: _entries(_NOTION))


def find_jira(site: str | None = None) -> StoredEntry[JiraCredentials] | None:
    origin = None if site is None else normalise_site(site)
    return _the_only_match(
        stored_jira_sign_ins(),
        origin,
        lambda entry, wanted: entry.identifier == wanted,
        "Jira sites",
        lambda entry: entry.identifier or _UNREADABLE_LEGACY_ENTRY,
    )


def find_notion(workspace: str | None = None) -> StoredEntry[NotionCredentials] | None:
    return _the_only_match(
        stored_notion_sign_ins(),
        workspace,
        _is_workspace,
        "Notion workspaces",
        _describe_workspace,
    )


def stored_notion_replaced_by(credentials: NotionCredentials) -> StoredEntry[NotionCredentials] | None:
    entries = stored_notion_sign_ins()
    same_workspace = _NOTION.identify(credentials)
    for entry in entries:
        if entry.identifier == same_workspace:
            return entry
    for entry in entries:
        if (
            entry.identifier == _UNIDENTIFIED_WORKSPACE
            and entry.credentials is not None
            and credentials.workspace_name is not None
            and entry.credentials.workspace_name == credentials.workspace_name
        ):
            return entry
    return None


def load_jira(site: str | None = None) -> SignIn[JiraCredentials] | None:
    from_environment = jira_from_environment()
    if from_environment is not None and (site is None or normalise_site(site) == from_environment.site):
        return SignIn(from_environment, "environment")
    return _signed_in(find_jira(site))


def load_notion(workspace: str | None = None) -> SignIn[NotionCredentials] | None:
    from_environment = notion_from_environment() if workspace is None else None
    if from_environment is not None:
        return SignIn(from_environment, "environment")
    return _signed_in(find_notion(workspace))


def require_jira(site: str | None = None) -> SignIn[JiraCredentials]:
    sign_in = load_jira(site)
    if sign_in is None:
        where = "" if site is None else f" at {normalise_site(site)}"
        raise AuthError(f"Not signed in to Jira{where}; run `skaldr auth jira`")
    return sign_in


def require_notion(workspace: str | None = None) -> SignIn[NotionCredentials]:
    sign_in = load_notion(workspace)
    if sign_in is None:
        where = "" if workspace is None else f" workspace {printable_only(workspace)}"
        raise AuthError(f"Not signed in to Notion{where}; run `skaldr auth notion`")
    return sign_in


def notion_client_from_environment() -> tuple[str | None, str | None]:
    return _environment(_NOTION_CLIENT_ID), _environment(_NOTION_CLIENT_SECRET)


def forget(entry: StoredEntry[Any]) -> None:
    def delete_and_unlist() -> None:
        _delete(entry.username)
        _unlist(entry.service, entry.username)

    _in_the_keychain(delete_and_unlist)


def _signed_in(entry: StoredEntry[CredentialsT] | None) -> SignIn[CredentialsT] | None:
    if entry is None:
        return None
    if entry.credentials is None:
        raise UnreadableEntryError(entry.unreadable_message)
    return SignIn(entry.credentials, "keychain")


def _the_only_match(
    entries: list[StoredEntry[CredentialsT]],
    selector: str | None,
    matches: Callable[[StoredEntry[CredentialsT], str], bool],
    plural: str,
    describe: Callable[[StoredEntry[CredentialsT]], str],
) -> StoredEntry[CredentialsT] | None:
    chosen = entries if selector is None else [entry for entry in entries if matches(entry, selector)]
    if len(chosen) > 1:
        raise AuthError(f"Signed in to several {plural} ({', '.join(map(describe, chosen))}); name one")
    return chosen[0] if chosen else None


def _is_workspace(entry: StoredEntry[NotionCredentials], selector: str) -> bool:
    return entry.identifier == selector or (
        entry.credentials is not None and entry.credentials.workspace_name == selector
    )


def _describe_workspace(entry: StoredEntry[NotionCredentials]) -> str:
    name = "" if entry.credentials is None else printable_only(entry.credentials.workspace_name or "")
    if not name:
        return entry.identifier or _UNREADABLE_LEGACY_ENTRY
    return name if entry.identifier is None else f"{name} ({entry.identifier})"


def _username(kind: _Kind[CredentialsT], credentials: CredentialsT) -> str:
    return f"{kind.service}:{kind.identify(credentials)}"


def _get(username: str) -> str | None:
    return keyring.get_password(KEYCHAIN_SERVICE, username)


def _set(username: str, secret: str) -> None:
    keyring.set_password(KEYCHAIN_SERVICE, username, secret)


def _delete(username: str) -> None:
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, username)
    except PasswordDeleteError:
        return


def _read_index() -> dict[Service, list[str]]:
    stored = _get(KEYCHAIN_INDEX_USERNAME)
    if stored is None:
        return {"jira": [], "notion": []}
    with CaughtWithoutChaining(ValidationError):
        listed = _INDEX_SHAPE.validate_json(stored)
        return {"jira": listed.get("jira", []), "notion": listed.get("notion", [])}
    raise AuthError(
        "The keychain index that lists the skaldr sign-ins is unreadable; remove the keychain entry "
        f"named {KEYCHAIN_INDEX_USERNAME} under {KEYCHAIN_SERVICE} and run `skaldr auth` again for each "
        "sign-in"
    )


def _list(service: Service, username: str) -> None:
    index = _read_index()
    if username not in index[service]:
        index[service].append(username)
        _set(KEYCHAIN_INDEX_USERNAME, json.dumps(index))


def _unlist(service: Service, username: str) -> None:
    index = _read_index()
    if username in index[service]:
        index[service].remove(username)
        _set(KEYCHAIN_INDEX_USERNAME, json.dumps(index))


def _parse(stored: str, model: type[CredentialsT]) -> CredentialsT | None:
    with CaughtWithoutChaining(ValidationError):
        return model.model_validate_json(stored)
    return None


def _migrate_legacy_entry(kind: _Kind[CredentialsT]) -> None:
    legacy = _get(kind.service)
    credentials = None if legacy is None else _parse(legacy, kind.model)
    if credentials is None:
        return
    username = _username(kind, credentials)
    if _get(username) is None:
        _set(username, credentials.model_dump_json())
    _list(kind.service, username)
    _delete(kind.service)


def _entries(kind: _Kind[CredentialsT]) -> list[StoredEntry[CredentialsT]]:
    _migrate_legacy_entry(kind)
    entries: list[StoredEntry[CredentialsT]] = []
    for username in [*_read_index()[kind.service], kind.service]:
        stored = _get(username)
        if stored is not None:
            entries.append(StoredEntry(kind.service, username, _parse(stored, kind.model)))
    return entries


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


def _in_the_keychain(operation: Callable[[], Answer]) -> Answer:
    with _keychain_errors_as_auth_errors():
        return _from_the_keychain(operation)


def refuse_an_unusable_keychain() -> None:
    _refuse_an_insecure_keyring()
    _in_the_keychain(lambda: _get(KEYCHAIN_INDEX_USERNAME))


def _save(kind: _Kind[CredentialsT], credentials: CredentialsT) -> None:
    _refuse_an_insecure_keyring()
    serialized = credentials.model_dump_json()
    username = _username(kind, credentials)

    def move_legacy_then_write() -> None:
        _migrate_legacy_entry(kind)
        _set(username, serialized)
        _list(kind.service, username)

    _in_the_keychain(move_legacy_then_write)


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


def notion_from_environment() -> NotionCredentials | None:
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


def jira_from_environment() -> JiraCredentials | None:
    values = _all_or_none_from_environment(JIRA_ENVIRONMENT)
    if values is None:
        return None
    with CaughtWithoutChaining(AuthError) as refused:
        return jira_credentials(values[_JIRA_SITE], values[_JIRA_EMAIL], values[_JIRA_API_TOKEN])
    raise AuthError(f"{_JIRA_SITE}: {refused.error}")
