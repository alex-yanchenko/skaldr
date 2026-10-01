import base64
import json
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from keyring.backend import KeyringBackend
from keyring.compat import properties
from keyring.errors import PasswordDeleteError

from skaldr.auth.store import JiraCredentials, NotionCredentials


class InMemoryKeyring(KeyringBackend):
    @properties.classproperty
    def priority(cls) -> float:
        return 0

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.entries.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


TOKEN_RESPONSE = {
    "access_token": "new-access",
    "token_type": "bearer",
    "refresh_token": "new-refresh",
    "bot_id": "bot-id",
    "workspace_id": "workspace-id",
    "workspace_name": "Example Workspace",
    "owner": {"type": "user"},
}


class FakeBrowser:
    def __init__(self, callback_query: Callable[[str], str] | None) -> None:
        self.callback_query = callback_query
        self.opened: list[str] = []

    def __call__(self, url: str) -> None:
        self.opened.append(url)
        if self.callback_query is None:
            return
        query = parse_qs(urlsplit(url).query)
        target = f"{query['redirect_uri'][0]}?{self.callback_query(query['state'][0])}"
        threading.Thread(target=httpx2.get, args=(target,), kwargs={"timeout": 5}).start()

    @property
    def redirect_uri(self) -> str:
        return parse_qs(urlsplit(self.opened[0]).query)["redirect_uri"][0]


def approving(state: str) -> str:
    return f"code=the-code&state={state}"


def fake_api(routes: dict[str, tuple[int, object]], seen: list[httpx2.Request]) -> httpx2.MockTransport:
    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        status, body = routes[request.url.path]
        return httpx2.Response(status, json=body)

    return httpx2.MockTransport(respond)


def summarise(request: httpx2.Request) -> dict[str, object]:
    return {
        "method": request.method,
        "url": str(request.url),
        "authorization": request.headers.get("authorization"),
        "content_type": request.headers.get("content-type"),
        "body": json.loads(request.content) if request.content else None,
    }


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def make_notion_credentials(**overrides: Any) -> NotionCredentials:
    fields: dict[str, Any] = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "workspace_name": "Example Workspace",
        "bot_id": "bot-id",
    }
    fields.update(overrides)
    return NotionCredentials.model_validate(fields)


def make_jira_credentials(**overrides: Any) -> JiraCredentials:
    fields: dict[str, Any] = {
        "site": "https://example.atlassian.net",
        "email": "reader@example.com",
        "api_token": "api-token",
        "display_name": "Example Reader",
    }
    fields.update(overrides)
    return JiraCredentials.model_validate(fields)
