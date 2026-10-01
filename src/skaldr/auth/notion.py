import json
import time
from collections.abc import Callable, Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import TracebackType
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx2
from authlib.common.errors import AuthlibBaseError
from authlib.integrations.httpx_client import OAuth2Client
from authlib.oauth2.auth import ClientAuth, encode_client_secret_basic
from pydantic import BaseModel, ValidationError
from typing_extensions import override

from skaldr.auth.store import NotionCredentials
from skaldr.errors import AuthError

NOTION_API = "https://api.notion.com"
INTEGRATIONS_PAGE = "https://www.notion.so/profile/integrations"
DEFAULT_CALLBACK_PORT = 8765
CALLBACK_PATH = "/callback"
SIGN_IN_TIMEOUT_SECONDS = 300.0
HTTP_TIMEOUT_SECONDS = 30.0
IDLE_CONNECTION_TIMEOUT_SECONDS = 5.0
BASIC_AUTH_WITH_JSON_BODY = "client_secret_basic_json"


class _NotionToken(BaseModel):
    access_token: str
    refresh_token: str | None = None
    workspace_name: str | None = None
    bot_id: str | None = None


def redirect_uri_for(port: int) -> str:
    return f"http://localhost:{port}{CALLBACK_PATH}"


def sign_in_to_notion(
    client_id: str,
    client_secret: str,
    *,
    open_browser: Callable[[str], object],
    port: int = DEFAULT_CALLBACK_PORT,
    transport: httpx2.BaseTransport | None = None,
    timeout_seconds: float = SIGN_IN_TIMEOUT_SECONDS,
) -> NotionCredentials:
    with _CallbackListener(port) as listener:
        redirect_uri = redirect_uri_for(listener.port)
        with _oauth_client(client_id, client_secret, transport, redirect_uri) as client:
            authorize_url, state = client.create_authorization_url(
                f"{NOTION_API}/v1/oauth/authorize", owner="user"
            )
            open_browser(authorize_url)
            query = listener.wait_for_callback(timeout_seconds)
            _refuse_a_denied_consent(query)
            token = _parse_token(
                lambda: client.fetch_token(
                    f"{NOTION_API}/v1/oauth/token",
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
        bot_id=token.bot_id,
    )


def refresh_notion_token(
    credentials: NotionCredentials, *, transport: httpx2.BaseTransport | None = None
) -> NotionCredentials:
    refresh_token = credentials.refresh_token
    if not (refresh_token and credentials.client_id and credentials.client_secret):
        raise AuthError("The Notion token cannot be refreshed; run `skaldr auth notion` again")
    with _oauth_client(credentials.client_id, credentials.client_secret, transport) as client:
        token = _parse_token(
            lambda: client.refresh_token(f"{NOTION_API}/v1/oauth/token", refresh_token=refresh_token)
        )
    return credentials.model_copy(
        update={"access_token": token.access_token, "refresh_token": token.refresh_token or refresh_token}
    )


def revoke_notion_token(
    credentials: NotionCredentials, *, transport: httpx2.BaseTransport | None = None
) -> None:
    if not (credentials.client_id and credentials.client_secret):
        raise AuthError("The Notion token cannot be revoked without the client ID and secret")
    with _oauth_client(credentials.client_id, credentials.client_secret, transport) as client:
        try:
            response = client.revoke_token(f"{NOTION_API}/v1/oauth/revoke", token=credentials.access_token)
        except httpx2.HTTPError as exc:
            raise AuthError(f"Could not reach Notion: {exc}") from exc
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
        token_endpoint_auth_method=BASIC_AUTH_WITH_JSON_BODY,
        revocation_endpoint_auth_method=BASIC_AUTH_WITH_JSON_BODY,
        redirect_uri=redirect_uri,
        transport=transport,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    client.register_client_auth_method((BASIC_AUTH_WITH_JSON_BODY, _basic_auth_with_json_body))
    return client


def _basic_auth_with_json_body(
    auth: ClientAuth, method: str, uri: str, headers: dict[str, str], body: str | bytes
) -> tuple[str, dict[str, str], str | bytes]:
    form = body.decode() if isinstance(body, bytes) else body
    headers["Content-Type"] = "application/json"
    return encode_client_secret_basic(auth, method, uri, headers, json.dumps(dict(parse_qsl(form))))


def _parse_token(request: Callable[[], Mapping[str, object]]) -> _NotionToken:
    try:
        return _NotionToken.model_validate(dict(request()))
    except AuthlibBaseError as exc:
        detail = f" ({exc.description})" if exc.description else ""
        raise AuthError(f"Notion refused the sign-in: {exc.error}{detail}") from exc
    except httpx2.HTTPError as exc:
        raise AuthError(f"Could not reach Notion: {exc}") from exc
    except ValidationError as exc:
        raise AuthError(f"Notion's token answer has no access token: {exc}") from exc
    except ValueError as exc:
        raise AuthError(f"Notion's token answer is not JSON: {exc}") from exc


def _refuse_a_denied_consent(query: str) -> None:
    error = parse_qs(query).get("error")
    if error:
        raise AuthError(f"Notion did not grant access: {error[0]}")


class _CallbackListener:
    def __init__(self, port: int) -> None:
        self.queries: list[str] = []
        try:
            self._server = HTTPServer(("127.0.0.1", port), _handler_recording_into(self.queries))
        except OSError as exc:
            raise AuthError(
                f"Port {port} is in use; free it or pass --port with the port in your registered redirect URI"
            ) from exc

    @property
    def port(self) -> int:
        return self._server.server_port

    def __enter__(self) -> "_CallbackListener":
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self._server.server_close()

    def wait_for_callback(self, timeout_seconds: float) -> str:
        deadline = time.monotonic() + timeout_seconds
        while not self.queries:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AuthError(
                    f"Timed out waiting for Notion to redirect back to {redirect_uri_for(self.port)} "
                    f"after {timeout_seconds:g} seconds"
                )
            self._server.timeout = remaining
            self._server.handle_request()
        return self.queries[0]


def _handler_recording_into(queries: list[str]) -> type[BaseHTTPRequestHandler]:
    class CallbackHandler(BaseHTTPRequestHandler):
        timeout = IDLE_CONNECTION_TIMEOUT_SECONDS

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path != CALLBACK_PATH:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            queries.append(url.query)
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
