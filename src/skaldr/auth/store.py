import json
import os
import sys
import threading
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, Literal, TypeVar, cast
from uuid import UUID

import keyring
from filelock import FileLock, Timeout
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, ValidationError, field_validator
from pydantic_core import PydanticCustomError

from skaldr.auth import CaughtWithoutChaining, printable_only
from skaldr.errors import AuthError
from skaldr.services import Service

KEYCHAIN_SERVICE = "skaldr"
KEYCHAIN_INDEX_USERNAME = "index"
LEGACY_SELECTOR = "legacy"
_NAME_ONE = "name one"
_NAME_THE_TARGET_WORKSPACE = "name one with `workspace` in the target's `where`"
LOCK_TIMEOUT_SECONDS = 30.0
_UNIDENTIFIED_WORKSPACE = "unidentified"
_UNREADABLE_LEGACY_ENTRY = "an unreadable entry"
_INDEX_SHAPE = TypeAdapter(dict[str, list[str]])
KEYCHAIN_NOTICE_SECONDS = 2.0
KEYCHAIN_TIMEOUT_SECONDS = 120.0
KEYCHAIN_WAIT_NOTICE = (
    "Waiting for the system keychain; if it is locked or shows a prompt for skaldr, "
    "unlock it or answer there."
)
LOCK_WAIT_NOTICE = "Waiting for another skaldr command to finish with the keychain."
Answer = TypeVar("Answer")

Source = Literal["keychain", "environment"]

NOTION_ACCESS_TOKEN_VARIABLE = "NOTION_ACCESS_TOKEN"
_NOTION_CLIENT_ID = "NOTION_CLIENT_ID"
_NOTION_CLIENT_SECRET = "NOTION_CLIENT_SECRET"
_NOTION_CLIENT_ENVIRONMENT = (_NOTION_CLIENT_ID, _NOTION_CLIENT_SECRET)
NOTION_ENVIRONMENT = (NOTION_ACCESS_TOKEN_VARIABLE, *_NOTION_CLIENT_ENVIRONMENT)
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
    client_secret: str | None = Field(repr=False)
    access_token: str = Field(repr=False)
    refresh_token: str | None = Field(repr=False)
    workspace_id: UUID | None = None
    workspace_name: str | None


class JiraCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    email: str
    api_token: str = Field(repr=False)
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
    legacy_replaces_keyed: bool


_JIRA = _Kind[JiraCredentials]("jira", JiraCredentials, lambda credentials: credentials.site, True)
_NOTION = _Kind[NotionCredentials](
    "notion",
    NotionCredentials,
    lambda credentials: (
        _UNIDENTIFIED_WORKSPACE if credentials.workspace_id is None else str(credentials.workspace_id)
    ),
    False,
)


@dataclass(frozen=True)
class StoredEntry(Generic[CredentialsT]):
    service: Service
    username: str
    credentials: CredentialsT | None
    raw: str = field(compare=False, repr=False)

    @property
    def identifier(self) -> str | None:
        prefix = f"{self.service}:"
        return self.username.removeprefix(prefix) if self.username.startswith(prefix) else None

    @property
    def unreadable_message(self) -> str:
        if self.identifier is None:
            return (
                f"The keychain entry for {self.service} is unreadable; run "
                f"`skaldr auth logout {self.service} {LEGACY_SELECTOR}` to remove it, then run "
                f"`skaldr auth {self.service}` again"
            )
        return (
            f"The keychain entry for {self.service} {self.identifier} is unreadable; "
            f"run `skaldr auth {self.service}` again"
        )


AnyStoredEntry = StoredEntry[JiraCredentials] | StoredEntry[NotionCredentials]


@dataclass(frozen=True)
class NotionReplacement:
    replaced: StoredEntry[NotionCredentials] | None
    older_sign_in_without_a_workspace_id: bool


def save_notion_returning_the_replaced(credentials: NotionCredentials) -> NotionReplacement:
    if credentials.workspace_id is None:
        raise AuthError("A Notion sign-in without a workspace id cannot be saved")
    _refuse_an_insecure_keyring()
    workspace = str(credentials.workspace_id)
    username = _username(_NOTION, credentials)

    def look_up_then_write() -> NotionReplacement:
        entries = _entries(_NOTION)
        replacement = NotionReplacement(
            entry_for_workspace(entries, credentials.workspace_id) or _entry_named(_NOTION, workspace),
            any(
                entry.credentials is not None and entry.credentials.workspace_id is None for entry in entries
            ),
        )
        _write(_NOTION, username, credentials)
        return replacement

    return _in_the_keychain(look_up_then_write)


def save_jira(credentials: JiraCredentials) -> None:
    _save(_JIRA, credentials)


def stored_jira_sign_ins() -> list[StoredEntry[JiraCredentials]]:
    return _in_the_keychain(lambda: _entries(_JIRA))


def stored_notion_sign_ins() -> list[StoredEntry[NotionCredentials]]:
    return _in_the_keychain(lambda: _entries(_NOTION))


def find_jira(site: str | None = None) -> StoredEntry[JiraCredentials] | None:
    names_an_origin = site is not None and site != LEGACY_SELECTOR
    wanted = normalise_site(site) if site is not None and names_an_origin else site
    found = _the_only_match(
        stored_jira_sign_ins(),
        wanted,
        _is_site,
        "Jira sites",
        lambda entry: entry.identifier or _UNREADABLE_LEGACY_ENTRY,
    )
    if found is None and wanted is not None and names_an_origin:
        return _in_the_keychain(lambda: _entry_named(_JIRA, wanted))
    return found


def find_notion(
    workspace: str | None = None, how_to_name_one: str = _NAME_ONE
) -> StoredEntry[NotionCredentials] | None:
    wanted = None if workspace is None else _canonical_workspace_selector(workspace)
    found = _the_only_match(
        stored_notion_sign_ins(),
        wanted,
        _is_workspace,
        "Notion workspaces",
        _describe_workspace,
        how_to_name_one,
    )
    if found is None and wanted is not None and _is_uuid(wanted):
        return _in_the_keychain(lambda: _entry_named(_NOTION, wanted))
    return found


def entry_for_workspace(
    entries: list[StoredEntry[NotionCredentials]], workspace_id: UUID | None
) -> StoredEntry[NotionCredentials] | None:
    if workspace_id is None:
        return None
    return next((entry for entry in entries if entry.identifier == str(workspace_id)), None)


def load_jira(site: str | None = None) -> SignIn[JiraCredentials] | None:
    from_environment = jira_from_environment()
    if from_environment is not None and (site is None or normalise_site(site) == from_environment.site):
        return SignIn(from_environment, "environment")
    return _signed_in(find_jira(site))


def load_notion(
    workspace: str | None = None, how_to_name_one: str = _NAME_ONE
) -> SignIn[NotionCredentials] | None:
    from_environment = notion_from_environment() if workspace is None else None
    if from_environment is not None:
        return SignIn(from_environment, "environment")
    return _signed_in(find_notion(workspace, how_to_name_one))


def require_notion_for_a_target(workspace: str | None) -> SignIn[NotionCredentials]:
    sign_in = load_notion(workspace, _NAME_THE_TARGET_WORKSPACE)
    if sign_in is not None:
        return sign_in
    signed_in = stored_notion_sign_ins()
    if workspace is None or not signed_in:
        return require_notion(workspace)
    raise AuthError(
        f"No Notion sign-in matches workspace `{printable_only(workspace)}`; signed in to "
        f"{', '.join(map(_describe_workspace, signed_in))}"
    )


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


def forget(entry: AnyStoredEntry) -> bool:
    def delete_unless_changed_then_unlist() -> bool:
        stored = _get(entry.username)
        if stored is not None and stored != entry.raw:
            return False
        _delete(entry.username)
        _unlist(entry.service, entry.username)
        return True

    return _in_the_keychain(delete_unless_changed_then_unlist)


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
    how_to_name_one: str = _NAME_ONE,
) -> StoredEntry[CredentialsT] | None:
    chosen = entries if selector is None else [entry for entry in entries if matches(entry, selector)]
    if len(chosen) > 1:
        raise AuthError(
            f"Signed in to several {plural} ({', '.join(map(describe, chosen))}); {how_to_name_one}"
        )
    return chosen[0] if chosen else None


def _is_site(entry: StoredEntry[JiraCredentials], selector: str) -> bool:
    return entry.identifier == selector or (selector == LEGACY_SELECTOR and entry.identifier is None)


def _is_workspace(entry: StoredEntry[NotionCredentials], selector: str) -> bool:
    return (
        entry.identifier == selector
        or (selector == LEGACY_SELECTOR and entry.identifier is None)
        or (entry.credentials is not None and entry.credentials.workspace_name == selector)
    )


def _is_uuid(text: str) -> bool:
    try:
        UUID(text)
    except ValueError:
        return False
    return True


def _canonical_workspace_selector(selector: str) -> str:
    return str(UUID(selector)) if _is_uuid(selector) else selector


def _entry_named(kind: _Kind[CredentialsT], identifier: str) -> StoredEntry[CredentialsT] | None:
    username = f"{kind.service}:{identifier}"
    stored = _get(username)
    if stored is None:
        return None
    _list(kind.service, username)
    return StoredEntry(kind.service, username, _parse(stored, kind.model), stored)


def _describe_workspace(entry: StoredEntry[NotionCredentials]) -> str:
    name = "" if entry.credentials is None else printable_only(entry.credentials.workspace_name or "")
    if not name:
        return entry.identifier or _UNREADABLE_LEGACY_ENTRY
    return name if entry.identifier is None else f"{name} ({entry.identifier})"


def _username(kind: _Kind[CredentialsT], credentials: CredentialsT) -> str:
    return f"{kind.service}:{kind.identify(credentials)}"


_operation = threading.local()


def _operation_backend() -> KeyringBackend:
    return cast("KeyringBackend", _operation.backend)


def _get(username: str) -> str | None:
    return _operation_backend().get_password(KEYCHAIN_SERVICE, username)


def _set(username: str, secret: str) -> None:
    backend = _operation_backend()
    _refuse_an_insecure_backend(backend)
    backend.set_password(KEYCHAIN_SERVICE, username, secret)  # pyright: ignore[reportUnknownMemberType]


def _delete(username: str) -> None:
    try:
        _operation_backend().delete_password(KEYCHAIN_SERVICE, username)
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
        f"named {KEYCHAIN_INDEX_USERNAME} under {KEYCHAIN_SERVICE}, then name each Jira site or Notion "
        "workspace to find its sign-in again"
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
    serialized = credentials.model_dump_json()
    username = _migration_username(kind, _username(kind, credentials), serialized)
    _set(username, serialized)
    _list(kind.service, username)
    _delete(kind.service)


def _migration_username(kind: _Kind[CredentialsT], preferred: str, serialized: str) -> str:
    if kind.legacy_replaces_keyed:
        return preferred
    candidate, number = preferred, 1
    while (existing := _get(candidate)) is not None and existing != serialized:
        number += 1
        candidate = f"{preferred}-{number}"
    return candidate


def _entries(kind: _Kind[CredentialsT]) -> list[StoredEntry[CredentialsT]]:
    _migrate_legacy_entry(kind)
    entries: list[StoredEntry[CredentialsT]] = []
    for username in [*_read_index()[kind.service], kind.service]:
        stored = _get(username)
        if stored is not None:
            entries.append(StoredEntry(kind.service, username, _parse(stored, kind.model), stored))
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


class KeychainTimeoutError(AuthError):
    pass


class KeychainWaitInterrupted(KeyboardInterrupt):
    pass


def _from_the_keychain(
    ask: Callable[[], Answer], still_waiting_for_the_lock: Callable[[], bool] = lambda: False
) -> Answer:
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
    try:
        if not answered.wait(KEYCHAIN_NOTICE_SECONDS):
            print(LOCK_WAIT_NOTICE if still_waiting_for_the_lock() else KEYCHAIN_WAIT_NOTICE, file=sys.stderr)
            if not answered.wait(KEYCHAIN_TIMEOUT_SECONDS - KEYCHAIN_NOTICE_SECONDS):
                raise KeychainTimeoutError(
                    f"The system keychain did not answer within {KEYCHAIN_TIMEOUT_SECONDS:g} seconds; "
                    "unlock it or answer its prompt, then run the command again. A change skaldr asked for "
                    "may still be applied if the keychain answers later"
                )
    except KeyboardInterrupt as interrupted:
        raise KeychainWaitInterrupted from interrupted
    if reply.error is not None:
        raise reply.error
    return cast("Answer", reply.value)


@contextmanager
def _keychain_errors_as_auth_errors() -> Generator[None, None, None]:
    try:
        yield
    except KeyringError as exc:
        raise AuthError(f"The system keychain is unavailable: {exc}") from exc


def state_directory() -> Path:
    configured = Path(os.environ.get("XDG_STATE_HOME", ""))
    base = configured if configured.is_absolute() else Path.home() / ".local" / "state"
    return base / "skaldr"


def lock_file() -> Path:
    directory = state_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / "auth.lock"


@dataclass
class _LockWait:
    waiting: bool = True


_holding_the_lock = threading.local()


def _under_the_lock(operation: Callable[[], Answer], wait: _LockWait, backend: KeyringBackend) -> Answer:
    try:
        lock = FileLock(lock_file())
        lock.acquire(timeout=LOCK_TIMEOUT_SECONDS)
    except Timeout as exc:
        raise AuthError(
            f"Another skaldr auth command has held the keychain lock for {LOCK_TIMEOUT_SECONDS:g} "
            "seconds; run this again when it finishes"
        ) from exc
    except OSError as exc:
        raise AuthError(f"skaldr cannot take its keychain lock in {state_directory()}: {exc}") from exc
    wait.waiting = False
    _holding_the_lock.held = True
    _operation.backend = backend
    try:
        return operation()
    finally:
        _holding_the_lock.held = False
        lock.release()


def _in_the_keychain(operation: Callable[[], Answer]) -> Answer:
    if getattr(_holding_the_lock, "held", False):
        return operation()
    wait = _LockWait()
    with _keychain_errors_as_auth_errors():
        backend = _from_the_keychain(keyring.get_keyring)
        return _from_the_keychain(lambda: _under_the_lock(operation, wait, backend), lambda: wait.waiting)


def refuse_an_unusable_keychain() -> None:
    _refuse_an_insecure_keyring()
    _in_the_keychain(_read_index)


def _save(kind: _Kind[CredentialsT], credentials: CredentialsT) -> None:
    _refuse_an_insecure_keyring()
    username = _username(kind, credentials)
    _in_the_keychain(lambda: _write(kind, username, credentials))


def _write(kind: _Kind[CredentialsT], username: str, credentials: CredentialsT) -> None:
    _migrate_legacy_entry(kind)
    _set(username, credentials.model_dump_json())
    _list(kind.service, username)


def _refuse_an_insecure_keyring() -> None:
    with _keychain_errors_as_auth_errors():
        backend = _from_the_keychain(keyring.get_keyring)
    _refuse_an_insecure_backend(backend)


def _refuse_an_insecure_backend(backend: KeyringBackend) -> None:
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
    access_token = _environment(NOTION_ACCESS_TOKEN_VARIABLE)
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
