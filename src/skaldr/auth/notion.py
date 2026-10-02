import errno
import json
import re
import secrets
import socket
import threading
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from types import TracebackType
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx2
from authlib.common.errors import AuthlibBaseError
from authlib.integrations.httpx_client import OAuth2Client
from authlib.oauth2.auth import ClientAuth, encode_client_secret_basic
from pydantic import BaseModel, ValidationError
from typing_extensions import Self, override

from skaldr.auth import HTTP_TIMEOUT_SECONDS, printable
from skaldr.auth.store import NotionCredentials
from skaldr.errors import AuthError

INTEGRATIONS_PAGE = "https://www.notion.so/profile/integrations"
DEFAULT_CALLBACK_PORT = 8765
SIGN_IN_TIMEOUT_SECONDS = 300.0

_NOTION_API = "https://api.notion.com"
CALLBACK_THREAD_PREFIX = "skaldr-notion-callback-"

_REDIRECT_HOST = "localhost"
_IPV4_LOOPBACK = "127.0.0.1"
_IPV6_LOOPBACK = "::1"
_NO_IPV6_LOOPBACK = frozenset({errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT})
_CALLBACK_PATH = "/callback"
_IDLE_CONNECTION_TIMEOUT_SECONDS = 5.0
_BASIC_AUTH_WITH_JSON_BODY = "client_secret_basic_json"
_OAUTH_ERROR_CODE = re.compile(r"[a-z_]+")


class _NotionToken(BaseModel):
    access_token: str
    refresh_token: str | None = None
    workspace_name: str | None = None


def redirect_uri_for(port: int) -> str:
    return f"http://{_REDIRECT_HOST}:{port}{_CALLBACK_PATH}"


def sign_in_to_notion(
    client_id: str,
    client_secret: str,
    *,
    open_browser: Callable[[str], object],
    port: int = DEFAULT_CALLBACK_PORT,
    transport: httpx2.BaseTransport | None = None,
    timeout_seconds: float = SIGN_IN_TIMEOUT_SECONDS,
) -> NotionCredentials:
    state = secrets.token_urlsafe(32)
    with _CallbackListener(port, state) as listener:
        redirect_uri = redirect_uri_for(listener.port)
        with _oauth_client(client_id, client_secret, transport, redirect_uri) as client:
            authorize_url, _ = client.create_authorization_url(
                f"{_NOTION_API}/v1/oauth/authorize", state=state, owner="user"
            )
            open_browser(authorize_url)
            query = listener.wait_for_callback(timeout_seconds)
            _refuse_a_denied_consent(query)
            token = _parse_token(
                lambda: client.fetch_token(
                    f"{_NOTION_API}/v1/oauth/token",
                    authorization_response=f"{redirect_uri}?{query}",
                    state=state,
                )
            )
    return NotionCredentials(
        client_id=client_id,
        client_secret=client_secret,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        workspace_name=token.workspace_name,
    )


def revoke_notion_token(
    credentials: NotionCredentials, *, transport: httpx2.BaseTransport | None = None
) -> None:
    if not (credentials.client_id and credentials.client_secret):
        raise AuthError("The Notion token cannot be revoked without the client ID and secret")
    with _oauth_client(credentials.client_id, credentials.client_secret, transport) as client:
        try:
            response = client.revoke_token(f"{_NOTION_API}/v1/oauth/revoke", token=credentials.access_token)
        except httpx2.HTTPError as exc:
            raise _unreachable(exc) from exc
    if response.status_code != HTTPStatus.OK:
        raise AuthError(f"Notion did not revoke the token: HTTP {response.status_code}")


def _oauth_client(
    client_id: str,
    client_secret: str,
    transport: httpx2.BaseTransport | None,
    redirect_uri: str | None = None,
) -> OAuth2Client:
    client = OAuth2Client(
        client_id,
        client_secret,
        token_endpoint_auth_method=_BASIC_AUTH_WITH_JSON_BODY,
        revocation_endpoint_auth_method=_BASIC_AUTH_WITH_JSON_BODY,
        redirect_uri=redirect_uri,
        transport=transport,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    client.register_client_auth_method((_BASIC_AUTH_WITH_JSON_BODY, _basic_auth_with_json_body))
    client.register_compliance_hook("access_token_response", _refuse_a_failed_token_status)
    return client


def _refuse_a_failed_token_status(response: httpx2.Response) -> httpx2.Response:
    failed = response.status_code >= HTTPStatus.BAD_REQUEST
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR or (
        failed and not _names_an_oauth_error(response)
    ):
        raise AuthError(f"Notion answered HTTP {response.status_code} for the token request")
    return response


def _names_an_oauth_error(response: httpx2.Response) -> bool:
    try:
        body: object = response.json()
    except json.JSONDecodeError:
        return False
    return isinstance(body, dict) and "error" in body


def _basic_auth_with_json_body(
    auth: ClientAuth, method: str, uri: str, headers: dict[str, str], body: str | bytes
) -> tuple[str, dict[str, str], str | bytes]:
    form = body.decode() if isinstance(body, bytes) else body
    headers["Content-Type"] = "application/json"
    return encode_client_secret_basic(auth, method, uri, headers, json.dumps(dict(parse_qsl(form))))


def _parse_token(request: Callable[[], Mapping[str, object]]) -> _NotionToken:
    try:
        return _NotionToken.model_validate(request())
    except AuthlibBaseError as exc:
        if exc.error == "invalid_client":
            raise AuthError(
                "Notion refused the client ID or secret (invalid_client); copy both from the connection "
                f"page at {INTEGRATIONS_PAGE} again"
            ) from exc
        detail = f" ({printable(exc.description)})" if exc.description else ""
        raise AuthError(f"Notion refused the sign-in: {printable(str(exc.error))}{detail}") from exc
    except httpx2.HTTPError as exc:
        raise _unreachable(exc) from exc
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors(include_input=False))
    except json.JSONDecodeError as exc:
        raise AuthError("Notion's token answer is not JSON") from exc
    raise AuthError(
        f"Notion's token answer is missing or has invalid fields: {fields or '(the whole answer)'}"
    )


def _unreachable(exc: httpx2.HTTPError) -> AuthError:
    return AuthError(f"Could not reach Notion: {exc}")


def _refuse_a_denied_consent(query: str) -> None:
    error = parse_qs(query).get("error")
    if not error:
        return
    if _OAUTH_ERROR_CODE.fullmatch(error[0]):
        raise AuthError(f"Notion did not grant access: {error[0]}")
    raise AuthError("Notion did not grant access")


class _LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    @override
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        self.server_name = _IPV4_LOOPBACK if self.address_family == socket.AF_INET else _IPV6_LOOPBACK
        self.server_port = self.socket.getsockname()[1]


class _IPv6LoopbackServer(_LoopbackServer):
    address_family = socket.AF_INET6


class _CallbackListener:
    def __init__(self, port: int, state: str) -> None:
        self._accepted: list[str] = []
        self._answered = threading.Event()
        handler = _callback_handler_class(state, self._accepted, self._answered)
        with ExitStack() as cleanup:
            ipv4 = _bind_ipv4_loopback(port, handler)
            cleanup.callback(ipv4.server_close)
            servers = [ipv4]
            ipv6 = _bind_ipv6_loopback(ipv4.server_port, handler)
            if ipv6 is not None:
                cleanup.callback(ipv6.server_close)
                servers.append(ipv6)
            for server in servers:
                family = "ipv4" if server is ipv4 else "ipv6"
                threading.Thread(
                    target=server.serve_forever,
                    kwargs={"poll_interval": 0.1},
                    name=f"{CALLBACK_THREAD_PREFIX}{family}",
                    daemon=True,
                ).start()
                cleanup.callback(server.shutdown)
            self._port = ipv4.server_port
            self._cleanup = cleanup.pop_all()

    @property
    def port(self) -> int:
        return self._port

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._cleanup.close()

    def wait_for_callback(self, timeout_seconds: float) -> str:
        if not self._answered.wait(timeout_seconds):
            raise AuthError(
                f"Timed out after {timeout_seconds:g} seconds waiting for Notion to redirect back to "
                f"{redirect_uri_for(self.port)}; run `skaldr auth notion` again"
            )
        return self._accepted[0]


def _bind_ipv4_loopback(port: int, handler: type[BaseHTTPRequestHandler]) -> _LoopbackServer:
    try:
        return _LoopbackServer((_IPV4_LOOPBACK, port), handler)
    except OSError as exc:
        raise _cannot_listen(_IPV4_LOOPBACK, port, exc) from exc


def _bind_ipv6_loopback(port: int, handler: type[BaseHTTPRequestHandler]) -> _LoopbackServer | None:
    try:
        return _IPv6LoopbackServer((_IPV6_LOOPBACK, port), handler)
    except OSError as exc:
        if exc.errno in _NO_IPV6_LOOPBACK:
            return None
        raise _cannot_listen(f"[{_IPV6_LOOPBACK}]", port, exc) from exc


def _cannot_listen(address: str, port: int, exc: OSError) -> AuthError:
    return AuthError(
        f"Cannot listen on {address}:{port} ({exc.strerror or exc}); free the port, or register a "
        "redirect URI with another port and pass it with --port"
    )


def _answers_this_sign_in(query: str, state: str) -> bool:
    fields = parse_qs(query)
    received_state = fields.get("state")
    state_matches = received_state is not None and secrets.compare_digest(
        received_state[0].encode(), state.encode()
    )
    return state_matches and ("code" in fields or "error" in fields)


def _callback_handler_class(
    state: str, accepted: list[str], answered: threading.Event
) -> type[BaseHTTPRequestHandler]:
    first_answer = threading.Lock()

    class CallbackHandler(BaseHTTPRequestHandler):
        timeout = _IDLE_CONNECTION_TIMEOUT_SECONDS

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path != _CALLBACK_PATH:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not _answers_this_sign_in(url.query, state):
                self.send_error(HTTPStatus.BAD_REQUEST, "This is not the sign-in skaldr started")
                return
            if not first_answer.acquire(blocking=False):
                self.send_error(HTTPStatus.CONFLICT, "skaldr already has this sign-in")
                return
            accepted.append(url.query)
            answered.set()
            page = b"skaldr has the sign-in. Close this tab and return to the terminal.\n"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        @override
        def log_message(self, format: str, *args: object) -> None:
            return

    return CallbackHandler
