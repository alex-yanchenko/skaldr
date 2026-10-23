import json
import logging
import os
import re
import threading
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Generic, Literal, NamedTuple, TypeAlias, TypeVar, cast
from uuid import UUID

import keyring
from filelock import FileLock, Timeout
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator
from pydantic_core import PydanticCustomError

from skaldr.auth import CaughtWithoutChaining, printable_only
from skaldr.auth.site import https_origin, normalise_site, site_refusal
from skaldr.errors import AuthError, SeveralSignInsError
from skaldr.services import SERVICE_NAMES, SERVICES, Service

_LOGGER = logging.getLogger(__name__)
KEYCHAIN_SERVICE = "skaldr"
KEYCHAIN_INDEX_USERNAME = "index"
LEGACY_SELECTOR = "legacy"
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
SLACK_USER_TOKEN_VARIABLE = "SLACK_USER_TOKEN"
SLACK_ENVIRONMENT = (SLACK_USER_TOKEN_VARIABLE,)
SLACK_USER_TOKEN_PREFIX = "xoxp-"
SLACK_TEAM_ID = re.compile(r"T[A-Z0-9]{2,}")
SLACK_ROTATING_TOKENS = (
    "A rotating token (xoxe.xoxp-...) expires and skaldr does not renew it, so it is not supported: use an "
    "app that does not rotate its tokens"
)
_ALWAYS_LISTED_SERVICES: tuple[Service, ...] = ("jira", "notion")
_INSECURE_KEYRING_MODULES = ("keyrings.alt", "keyring.backends.null", "keyring.backends.fail")


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
        origin = https_origin(site)
        if origin is None:
            raise PydanticCustomError("https_origin", "{refusal}", {"refusal": site_refusal(site)})
        return origin


def is_slack_user_token(token: str) -> bool:
    return token.startswith(SLACK_USER_TOKEN_PREFIX)


def slack_token_refusal() -> str:
    return (
        f"skaldr signs in to Slack with a user token, which starts with {SLACK_USER_TOKEN_PREFIX}; copy the "
        f"User OAuth Token from your Slack app's OAuth & Permissions page. {SLACK_ROTATING_TOKENS}"
    )


class SlackCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str = Field(repr=False)
    team_id: str | None = None
    team_name: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    url: str | None = None

    @field_validator("access_token")
    @classmethod
    def _is_a_user_token(cls, access_token: str) -> str:
        if not is_slack_user_token(access_token):
            raise PydanticCustomError("user_token", "{refusal}", {"refusal": slack_token_refusal()})
        return access_token


CredentialsT = TypeVar("CredentialsT", NotionCredentials, JiraCredentials, SlackCredentials)


@dataclass(frozen=True)
class SignIn(Generic[CredentialsT]):
    credentials: CredentialsT
    source: Source


def jira_credentials(
    site: str, email: str, api_token: str, display_name: str | None = None, *, refusal_prefix: str = ""
) -> JiraCredentials:
    with CaughtWithoutChaining(ValidationError) as invalid:
        return JiraCredentials(site=site, email=email, api_token=api_token, display_name=display_name)
    raise AuthError(f"{refusal_prefix}{_first_refusal(invalid.error)}")


def _first_refusal(invalid: ValidationError) -> str:
    return invalid.errors(include_input=False)[0]["msg"]


def jira_selector(site: str | None) -> str | None:
    return site if site is None or site == LEGACY_SELECTOR else normalise_site(site)


@dataclass(frozen=True)
class _Kind(Generic[CredentialsT]):
    service: Service
    model: type[CredentialsT]
    identify: Callable[[CredentialsT], str]
    legacy_replaces_keyed: bool
    shown_name: Callable[[CredentialsT], str | None]


_JIRA = _Kind[JiraCredentials](
    "jira",
    JiraCredentials,
    lambda credentials: credentials.site,
    True,
    lambda credentials: credentials.display_name,
)
_NOTION = _Kind[NotionCredentials](
    "notion",
    NotionCredentials,
    lambda credentials: (
        _UNIDENTIFIED_WORKSPACE if credentials.workspace_id is None else str(credentials.workspace_id)
    ),
    False,
    lambda credentials: credentials.workspace_name,
)
_SLACK = _Kind[SlackCredentials](
    "slack",
    SlackCredentials,
    lambda credentials: credentials.team_id or _UNIDENTIFIED_WORKSPACE,
    False,
    lambda credentials: credentials.team_name,
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
        if not _a_sign_in_writes_an_entry_named(self.service, self.identifier):
            return (
                f"The keychain entry for {self.service} {self.identifier} is unreadable; "
                f"run `skaldr auth logout {self.service} {self.identifier}` to remove it"
            )
        return (
            f"The keychain entry for {self.service} {self.identifier} is unreadable; "
            f"run `skaldr auth {self.service}` again"
        )


AnyStoredEntry = StoredEntry[JiraCredentials] | StoredEntry[NotionCredentials] | StoredEntry[SlackCredentials]


def _a_sign_in_writes_an_entry_named(service: Service, identifier: str) -> bool:
    if service == "jira":
        return https_origin(identifier) == identifier
    if service == "slack":
        return SLACK_TEAM_ID.fullmatch(identifier) is not None
    return _is_uuid(identifier) and _canonical_workspace_selector(identifier) == identifier


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
        _discard_the_reads_so_far()
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


def save_slack(credentials: SlackCredentials) -> None:
    if credentials.team_id is None:
        raise AuthError("A Slack sign-in without a workspace id cannot be saved")
    _save(_SLACK, credentials)


def stored_slack_sign_ins() -> list[StoredEntry[SlackCredentials]]:
    return _in_the_keychain(lambda: _entries(_SLACK))


def find_slack(workspace: str | None = None) -> StoredEntry[SlackCredentials] | None:
    found = _the_only_workspace(_SLACK, stored_slack_sign_ins(), workspace)
    if found is None and workspace is not None and SLACK_TEAM_ID.fullmatch(workspace):
        return _in_the_keychain(lambda: _entry_named(_SLACK, workspace))
    return found


def load_slack(workspace: str | None = None) -> SignIn[SlackCredentials] | None:
    from_environment = slack_from_environment() if workspace is None else None
    if from_environment is not None:
        return SignIn(from_environment, "environment")
    return _signed_in(find_slack(workspace))


def require_slack_for_a_target(workspace: str | None) -> SignIn[SlackCredentials]:
    return _required_for_a_target(_SLACK, load_slack, workspace)


def slack_from_environment() -> SlackCredentials | None:
    access_token = _environment(SLACK_USER_TOKEN_VARIABLE)
    if access_token is None:
        return None
    if not is_slack_user_token(access_token):
        raise AuthError(f"{SLACK_USER_TOKEN_VARIABLE}: {slack_token_refusal()}")
    return SlackCredentials(access_token=access_token)


def _shown_name(kind: _Kind[CredentialsT], entry: StoredEntry[CredentialsT]) -> str:
    return "" if entry.credentials is None else printable_only(kind.shown_name(entry.credentials) or "")


def _is_the_workspace(kind: _Kind[CredentialsT], entry: StoredEntry[CredentialsT], selector: str) -> bool:
    if entry.identifier == selector or (selector == LEGACY_SELECTOR and entry.identifier is None):
        return True
    shown = _shown_name(kind, entry)
    return shown != "" and shown == printable_only(selector)


def _workspace_described(kind: _Kind[CredentialsT], entry: StoredEntry[CredentialsT]) -> str:
    name = _shown_name(kind, entry)
    if not name:
        return entry.identifier or _UNREADABLE_LEGACY_ENTRY
    return name if entry.identifier is None else f"{name} ({entry.identifier})"


def _the_only_workspace(
    kind: _Kind[CredentialsT], entries: list[StoredEntry[CredentialsT]], selector: str | None
) -> StoredEntry[CredentialsT] | None:
    return _the_only_match(
        entries,
        selector,
        lambda entry, wanted: _is_the_workspace(kind, entry, wanted),
        f"{SERVICE_NAMES[kind.service]} workspaces",
        lambda entry: _workspace_described(kind, entry),
    )


def _required_for_a_target(
    kind: _Kind[CredentialsT],
    load: Callable[[str | None], SignIn[CredentialsT] | None],
    workspace: str | None,
) -> SignIn[CredentialsT]:
    try:
        sign_in = load(workspace)
    except SeveralSignInsError as exc:
        raise AuthError(f"{exc} with `workspace` in the target's `where`") from exc
    if sign_in is not None:
        return sign_in
    signed_in = _in_the_keychain(lambda: _entries(kind))
    name = SERVICE_NAMES[kind.service]
    if workspace is None or not signed_in:
        where = "" if workspace is None else f" workspace {printable_only(workspace)}"
        raise AuthError(f"Not signed in to {name}{where}; run `skaldr auth {kind.service}`")
    raise AuthError(
        f"No {name} sign-in matches workspace `{printable_only(workspace)}`; signed in to "
        f"{', '.join(_workspace_described(kind, entry) for entry in signed_in)}"
    )


class JiraLookup(NamedTuple):
    selector: str | None
    entry: StoredEntry[JiraCredentials] | None


def find_jira(site: str | None = None) -> JiraLookup:
    entries = stored_jira_sign_ins()
    stored_under_the_typed_name = site is not None and any(entry.identifier == site for entry in entries)
    selector = site if stored_under_the_typed_name else jira_selector(site)
    return JiraLookup(selector, _find_jira_among(entries, selector))


def _find_jira_among(
    entries: list[StoredEntry[JiraCredentials]], wanted: str | None
) -> StoredEntry[JiraCredentials] | None:
    found = _the_only_match(
        entries,
        wanted,
        _is_site,
        "Jira sites",
        lambda entry: entry.identifier or _UNREADABLE_LEGACY_ENTRY,
    )
    if found is None and wanted is not None and wanted != LEGACY_SELECTOR:
        return _in_the_keychain(lambda: _entry_named(_JIRA, wanted))
    return found


def find_notion(
    workspace: str | None = None, *, reread: bool = False
) -> StoredEntry[NotionCredentials] | None:
    if reread:
        _discard_the_reads_so_far()
    wanted = None if workspace is None else _canonical_workspace_selector(workspace)
    found = _the_only_workspace(_NOTION, stored_notion_sign_ins(), wanted)
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
    return _load_jira_by_selector(jira_selector(site))


def _load_jira_by_selector(wanted: str | None) -> SignIn[JiraCredentials] | None:
    from_environment = jira_from_environment()
    if from_environment is not None and wanted in (None, from_environment.site):
        return SignIn(from_environment, "environment")
    return _signed_in(_find_jira_among(stored_jira_sign_ins(), wanted))


def load_notion(workspace: str | None = None) -> SignIn[NotionCredentials] | None:
    from_environment = notion_from_environment() if workspace is None else None
    if from_environment is not None:
        return SignIn(from_environment, "environment")
    return _signed_in(find_notion(workspace))


def require_notion_for_a_target(workspace: str | None) -> SignIn[NotionCredentials]:
    return _required_for_a_target(_NOTION, load_notion, workspace)


def require_jira(site: str | None = None) -> SignIn[JiraCredentials]:
    wanted = jira_selector(site)
    sign_in = _load_jira_by_selector(wanted)
    if sign_in is None:
        where = "" if wanted is None else f" at {wanted}"
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
        stored = _get_afresh(entry.username)
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
) -> StoredEntry[CredentialsT] | None:
    chosen = entries if selector is None else [entry for entry in entries if matches(entry, selector)]
    if len(chosen) > 1:
        named = "" if selector is None else f" named `{printable_only(selector)}`"
        by_its_id = "" if selector is None else " by its id"
        raise SeveralSignInsError(
            f"Signed in to several {plural}{named} ({', '.join(map(describe, chosen))}); name one{by_its_id}"
        )
    return chosen[0] if chosen else None


def _is_site(entry: StoredEntry[JiraCredentials], selector: str) -> bool:
    return entry.identifier == selector or (selector == LEGACY_SELECTOR and entry.identifier is None)


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


def _username(kind: _Kind[CredentialsT], credentials: CredentialsT) -> str:
    return f"{kind.service}:{kind.identify(credentials)}"


_operation = threading.local()


def _operation_backend() -> KeyringBackend:
    return cast("KeyringBackend", _operation.backend)


@dataclass
class _ReadsOfOneCommand:
    remembered: dict[str, str | None] | None = None


_command_reads = _ReadsOfOneCommand()


@contextmanager
def reading_each_keychain_item_once() -> Generator[None, None, None]:
    if _command_reads.remembered is not None:
        yield
        return
    _command_reads.remembered = {}
    try:
        yield
    finally:
        _command_reads.remembered = None


def _discard_the_reads_so_far() -> None:
    if _command_reads.remembered is not None:
        _command_reads.remembered.clear()


def _remember(username: str, stored: str | None) -> None:
    if _command_reads.remembered is not None:
        _command_reads.remembered[username] = stored


def _forget_the_read_of(username: str) -> None:
    if _command_reads.remembered is not None:
        _command_reads.remembered.pop(username, None)


def _get(username: str) -> str | None:
    remembered = _command_reads.remembered
    if remembered is not None and username in remembered:
        return remembered[username]
    stored = _operation_backend().get_password(KEYCHAIN_SERVICE, username)
    _remember(username, stored)
    return stored


def _get_afresh(username: str) -> str | None:
    _forget_the_read_of(username)
    return _get(username)


def _set(username: str, secret: str) -> None:
    backend = _operation_backend()
    _refuse_an_insecure_backend(backend)
    _forget_the_read_of(username)
    backend.set_password(KEYCHAIN_SERVICE, username, secret)  # pyright: ignore[reportUnknownMemberType]
    _remember(username, secret)


def _delete(username: str) -> None:
    _forget_the_read_of(username)
    with suppress(PasswordDeleteError):
        _operation_backend().delete_password(KEYCHAIN_SERVICE, username)
    _remember(username, None)


def _read_index(*, afresh: bool = False) -> dict[Service, list[str]]:
    stored = _get_afresh(KEYCHAIN_INDEX_USERNAME) if afresh else _get(KEYCHAIN_INDEX_USERNAME)
    if stored is None:
        return {service: [] for service in sorted(SERVICES)}
    with CaughtWithoutChaining(ValidationError):
        listed = _INDEX_SHAPE.validate_json(stored)
        return {service: listed.get(service, []) for service in sorted(SERVICES)}
    raise AuthError(
        "The keychain index that lists the skaldr sign-ins is unreadable; remove the keychain entry "
        f"named {KEYCHAIN_INDEX_USERNAME} under {KEYCHAIN_SERVICE}, then name each Jira site, Notion "
        "workspace or Slack workspace to find its sign-in again"
    )


def _write_index(index: dict[Service, list[str]]) -> None:
    written = {
        service: usernames
        for service, usernames in index.items()
        if usernames or service in _ALWAYS_LISTED_SERVICES
    }
    _set(KEYCHAIN_INDEX_USERNAME, json.dumps(written))


def _list(service: Service, username: str) -> None:
    index = _read_index(afresh=True)
    if username not in index[service]:
        index[service].append(username)
        _write_index(index)


def _unlist(service: Service, username: str) -> None:
    index = _read_index(afresh=True)
    if username in index[service]:
        index[service].remove(username)
        _write_index(index)


def _parse(stored: str, model: type[CredentialsT]) -> CredentialsT | None:
    with CaughtWithoutChaining(ValidationError):
        return model.model_validate_json(stored)
    return None


def _migrate_legacy_entry(kind: _Kind[CredentialsT]) -> None:
    legacy = _get(kind.service)
    credentials = None if legacy is None else _parse(legacy, kind.model)
    if credentials is None:
        return
    username = _migration_username(kind, _username(kind, credentials), credentials.model_dump_json())
    _write(kind, username, credentials)
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


@dataclass(frozen=True)
class _Answered(Generic[Answer]):
    value: Answer


_KeychainReply: TypeAlias = _Answered[Answer] | BaseException


class KeychainTimeoutError(AuthError):
    pass


class KeychainWaitInterrupted(KeyboardInterrupt):
    pass


def _from_the_keychain(
    ask: Callable[[], Answer], still_waiting_for_the_lock: Callable[[], bool] = lambda: False
) -> Answer:
    replies: SimpleQueue[_KeychainReply[Answer]] = SimpleQueue()

    def ask_and_record() -> None:
        try:
            replies.put(_Answered(ask()))
        except BaseException as exc:
            replies.put(exc)

    threading.Thread(target=ask_and_record, name="skaldr-keychain", daemon=True).start()
    try:
        reply = _wait_for_the_reply(replies, still_waiting_for_the_lock)
    except KeyboardInterrupt as interrupted:
        raise KeychainWaitInterrupted from interrupted
    if isinstance(reply, BaseException):
        raise reply
    return reply.value


def _wait_for_the_reply(
    replies: SimpleQueue[_KeychainReply[Answer]], still_waiting_for_the_lock: Callable[[], bool]
) -> _KeychainReply[Answer]:
    with suppress(Empty):
        return replies.get(timeout=KEYCHAIN_NOTICE_SECONDS)
    _LOGGER.warning(LOCK_WAIT_NOTICE if still_waiting_for_the_lock() else KEYCHAIN_WAIT_NOTICE)
    with suppress(Empty):
        return replies.get(timeout=max(0.0, KEYCHAIN_TIMEOUT_SECONDS - KEYCHAIN_NOTICE_SECONDS))
    raise KeychainTimeoutError(
        f"The system keychain did not answer within {KEYCHAIN_TIMEOUT_SECONDS:g} seconds; "
        "unlock it or answer its prompt, then run the command again. A change skaldr asked for "
        "may still be applied if the keychain answers later"
    )


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

    def migrate_then_write() -> None:
        _migrate_legacy_entry(kind)
        _write(kind, username, credentials)

    _in_the_keychain(migrate_then_write)


def _write(kind: _Kind[CredentialsT], username: str, credentials: CredentialsT) -> None:
    _list(kind.service, username)
    _set(username, credentials.model_dump_json())


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
    return jira_credentials(
        values[_JIRA_SITE],
        values[_JIRA_EMAIL],
        values[_JIRA_API_TOKEN],
        refusal_prefix=f"{_JIRA_SITE}: ",
    )
