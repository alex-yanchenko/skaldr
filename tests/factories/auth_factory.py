import base64
import json
import socket
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import null
from keyring.compat import properties
from keyring.errors import KeyringError, PasswordDeleteError
from typing_extensions import override

from skaldr.auth.store import (
    CredentialsT,
    JiraCredentials,
    NotionCredentials,
    StoredEntry,
    save_notion_returning_the_replaced,
)
from skaldr.services import Service

WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
OTHER_WORKSPACE_ID = "22222222-2222-4222-8222-222222222222"
HEX_WORKSPACE_ID = "abcdef01-2345-4678-89ab-cdef01234567"
SITE_WITH_A_PASSWORD = "https://a:secret-password@b.atlassian.net"


def rendered_traceback(error: BaseException) -> str:
    return "".join(traceback.format_exception(error))


def assert_secret_not_in_error_chain(error: BaseException, secret: str) -> None:
    secret_is_shown = secret in rendered_traceback(error)
    assert (secret_is_shown, error.__cause__, error.__context__) == (False, None, None)


class InMemoryKeyring(KeyringBackend):
    @properties.classproperty
    def priority(cls) -> float:
        return 0

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[tuple[str, str], str] = {}

    @override
    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    @override
    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    @override
    def delete_password(self, service: str, username: str) -> None:
        if self.entries.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


class PlaintextKeyring(InMemoryKeyring):
    __module__ = "keyrings.alt.file"


class PlaintextKeyringSubclass(PlaintextKeyring):
    pass


class NullKeyringSubclass(null.Keyring):
    pass


class ReadRecordingKeyring(InMemoryKeyring):
    def __init__(self) -> None:
        super().__init__()
        self.reads: list[tuple[str, str]] = []

    @override
    def get_password(self, service: str, username: str) -> str | None:
        self.reads.append((service, username))
        return super().get_password(service, username)


class WriteFailingKeyring(InMemoryKeyring):
    def __init__(self, failure: BaseException) -> None:
        super().__init__()
        self.failure = failure

    @override
    def set_password(self, service: str, username: str, password: str) -> None:
        raise self.failure


def insecure_keyring_refusal(backend_name: str) -> str:
    return (
        f"skaldr will not save to the keyring backend {backend_name}: the keyrings.alt backends store "
        "secrets where skaldr cannot vouch for them, and the null and fail backends store nothing. Choose a "
        "secure backend with the PYTHON_KEYRING_BACKEND environment variable or keyring's keyringrc.cfg, "
        "for example keyring.backends.macOS.Keyring, keyring.backends.Windows.WinVaultKeyring or "
        "keyring.backends.SecretService.Keyring"
    )


class SlowKeyring(InMemoryKeyring):
    def __init__(self, answers_after: float) -> None:
        super().__init__()
        self.answers_after = answers_after
        self.released = threading.Event()

    @override
    def get_password(self, service: str, username: str) -> str | None:
        self.released.wait(self.answers_after)
        return super().get_password(service, username)

    @override
    def set_password(self, service: str, username: str, password: str) -> None:
        self.released.wait(self.answers_after)
        self.entries[(service, username)] = password

    @override
    def delete_password(self, service: str, username: str) -> None:
        self.released.wait(self.answers_after)
        super().delete_password(service, username)


class LockedKeyring(KeyringBackend):
    @properties.classproperty
    def priority(cls) -> float:
        return 0

    @override
    def get_password(self, service: str, username: str) -> str | None:
        raise KeyringError("locked")

    @override
    def set_password(self, service: str, username: str, password: str) -> None:
        raise KeyringError("locked")

    @override
    def delete_password(self, service: str, username: str) -> None:
        raise KeyringError("locked")


TOKEN_RESPONSE: dict[str, object] = {
    "access_token": "new-access",
    "token_type": "bearer",
    "refresh_token": "new-refresh",
    "bot_id": "bot-id",
    "workspace_id": "11111111-1111-4111-8111-111111111111",
    "workspace_name": "Example Workspace",
    "owner": {"type": "user"},
}

MYSELF: dict[str, object] = {
    "accountId": "account-id",
    "displayName": "Example Reader",
    "emailAddress": "reader@example.com",
}

Visit = Callable[[str], str]


def site_refusal(typed: str) -> str:
    return f"The Jira site must be an https URL like https://<site>.atlassian.net, not {typed!r}"


USERINFO_REFUSAL = (
    "The Jira site must be an https URL like https://<site>.atlassian.net, with no user name or password "
    "before the host"
)


@dataclass(frozen=True)
class RefusedSite:
    case: str
    typed: str
    carries_userinfo: bool = False

    @property
    def refusal(self) -> str:
        return USERINFO_REFUSAL if self.carries_userinfo else site_refusal(self.typed)


REFUSED_SITES = (
    RefusedSite("userinfo that reads as the site", "acme.atlassian.net@evil.example", carries_userinfo=True),
    RefusedSite(
        "userinfo after the scheme", "https://acme.atlassian.net@evil.example", carries_userinfo=True
    ),
    RefusedSite(
        "a user name and password", "https://reader:secret@acme.atlassian.net", carries_userinfo=True
    ),
    RefusedSite(
        "a fragment before the site", "https://evil.example#@acme.atlassian.net", carries_userinfo=True
    ),
    RefusedSite(
        "a backslash before the site", "https://evil.example\\@acme.atlassian.net", carries_userinfo=True
    ),
    RefusedSite(
        "a backslash after the site", "https://acme.atlassian.net\\@evil.example", carries_userinfo=True
    ),
    RefusedSite("a backslash for a slash", "https://acme.atlassian.net\\jira"),
    RefusedSite("a query", "https://acme.atlassian.net/?next=/jira"),
    RefusedSite("a fragment", "https://acme.atlassian.net/jira#top"),
    RefusedSite("an ip literal", "https://127.0.0.1"),
    RefusedSite("an ipv6 literal", "https://[::1]"),
    RefusedSite("localhost with a port", "localhost:22"),
    RefusedSite("a host outside atlassian.net", "https://evil.example"),
    RefusedSite("atlassian.net itself", "https://atlassian.net"),
    RefusedSite("atlassian.net inside another host", "https://acme.atlassian.net.evil.example"),
)

SITE_REFUSALS = [pytest.param(site.typed, site.refusal, id=site.case) for site in REFUSED_SITES]
SITES_OFF_JIRA_CLOUD = [pytest.param(site.typed, id=site.case) for site in REFUSED_SITES]


def approving(state: str) -> str:
    return f"/callback?code=the-code&state={state}"


def refusing(state: str) -> str:
    return f"/callback?error=access_denied&state={state}"


def refusing_without_state(_state: str) -> str:
    return "/callback?error=access_denied"


def refusing_with_an_escape_sequence(state: str) -> str:
    return f"/callback?error=%1b%5b2J%1b%5bHPaste+your+client+secret&state={state}"


def forged_refusal(_state: str) -> str:
    return "/callback?error=access_denied&state=forged"


def approving_without_state(_state: str) -> str:
    return "/callback?code=the-code"


def forged(_state: str) -> str:
    return "/callback?code=the-code&state=forged"


def answerless(state: str) -> str:
    return f"/callback?state={state}"


def favicon(_state: str) -> str:
    return "/favicon.ico"


class FakeBrowser:
    def __init__(self, *visits: Visit, resolves_localhost_to: str = "127.0.0.1") -> None:
        self.visits = visits
        self.resolves_localhost_to = resolves_localhost_to
        self.opened: list[str] = []
        self.statuses: list[int] = []
        self.failures: list[BaseException] = []
        self._thread: threading.Thread | None = None

    def __call__(self, url: str) -> None:
        self.opened.append(url)
        query = parse_qs(urlsplit(url).query)
        redirect = urlsplit(query["redirect_uri"][0])
        host = (
            f"[{self.resolves_localhost_to}]"
            if ":" in self.resolves_localhost_to
            else self.resolves_localhost_to
        )
        origin = f"{redirect.scheme}://{host}:{redirect.port}"
        targets = [origin + visit(query["state"][0]) for visit in self.visits]
        self._thread = threading.Thread(target=self._visit_in_order, args=(targets,), daemon=True)
        self._thread.start()

    def _visit_in_order(self, targets: list[str]) -> None:
        try:
            with httpx2.Client(trust_env=False, timeout=5) as client:
                for target in targets:
                    self.statuses.append(client.get(target).status_code)
        except httpx2.HTTPError as exc:
            self.failures.append(exc)

    def finished(self) -> list[int]:
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self.failures:
            pytest.fail(f"the fake browser could not reach the callback server: {self.failures}")
        return self.statuses

    @property
    def redirect_uri(self) -> str:
        return parse_qs(urlsplit(self.opened[0]).query)["redirect_uri"][0]


def fake_api(routes: dict[str, tuple[int, object]], seen: list[httpx2.Request]) -> httpx2.MockTransport:
    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        status, body = routes[request.url.path]
        if isinstance(body, bytes):
            return httpx2.Response(status, content=body)
        return httpx2.Response(status, json=body)

    return httpx2.MockTransport(respond)


def refusing_connections(seen: list[httpx2.Request] | None = None) -> httpx2.MockTransport:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        raise httpx2.ConnectError("connection refused", request=request)

    return httpx2.MockTransport(refuse)


def revoke_request_for(access_token: str) -> dict[str, object]:
    return {
        "method": "POST",
        "url": "https://api.notion.com/v1/oauth/revoke",
        "authorization": basic_auth_header("client-id", "client-secret"),
        "content_type": "application/json",
        "body": {"token": access_token},
    }


def summarise(request: httpx2.Request) -> dict[str, object]:
    return {
        "method": request.method,
        "url": str(request.url),
        "authorization": request.headers.get("authorization"),
        "content_type": request.headers.get("content-type"),
        "body": json.loads(request.content) if request.content else None,
    }


def basic_auth_header(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def _free_on_ipv6_loopback(port: int) -> bool:
    try:
        with socket.create_server(("::1", port), family=socket.AF_INET6):
            return True
    except OSError:
        return False


IPV6_LOOPBACK = _free_on_ipv6_loopback(0)
needs_ipv6_loopback = pytest.mark.skipif(not IPV6_LOOPBACK, reason="this machine has no IPv6 loopback")


def free_port() -> int:
    for _ in range(20):
        with socket.create_server(("127.0.0.1", 0)) as probe:
            port: int = probe.getsockname()[1]
            if not IPV6_LOOPBACK or _free_on_ipv6_loopback(port):
                return port
    raise OSError("no port is free on both loopback addresses")


def make_notion_credentials(**overrides: str | None) -> NotionCredentials:
    fields: dict[str, str | None] = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "workspace_name": "Example Workspace",
    }
    _refuse_unknown_fields(overrides, fields)
    return NotionCredentials.model_validate({**fields, **overrides})


def legacy_entry_json(credentials: NotionCredentials | JiraCredentials) -> str:
    return credentials.model_dump_json(exclude={"workspace_id"})


def stored_entry(
    service: Service, username: str, credentials: CredentialsT | None
) -> StoredEntry[CredentialsT]:
    raw = "not json" if credentials is None else credentials.model_dump_json()
    return StoredEntry(service, username, credentials, raw)


def seed_notion(credentials: NotionCredentials) -> None:
    save_notion_returning_the_replaced(credentials)


class SlowSaveKeyring(InMemoryKeyring):
    def __init__(self) -> None:
        super().__init__()
        self.released = threading.Event()

    @override
    def set_password(self, service: str, username: str, password: str) -> None:
        self.released.wait(5)
        self.entries[(service, username)] = password


def make_jira_credentials(**overrides: str | None) -> JiraCredentials:
    fields: dict[str, str | None] = {
        "site": "https://example.atlassian.net",
        "email": "reader@example.com",
        "api_token": "api-token",
        "display_name": "Example Reader",
    }
    _refuse_unknown_fields(overrides, fields)
    return JiraCredentials.model_validate({**fields, **overrides})


def _refuse_unknown_fields(overrides: dict[str, str | None], fields: dict[str, str | None]) -> None:
    unknown = sorted(set(overrides) - set(fields))
    if unknown:
        raise TypeError(f"no such credential fields: {unknown}")
