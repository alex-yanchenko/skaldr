import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx2

from skaldr.publish.notion.api import NotionApi
from skaldr.publish.notion.transport import NotionTransport
from skaldr.publish_block import notion_page_id

BOT_ID = "b0b0b0b0-0000-4000-8000-000000000001"
PERSON_ID = "9e9e9e9e-0000-4000-8000-000000000002"
FIRST_EDIT = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
TITLE_NAME = "Name"
DATABASE_SCHEMA = {TITLE_NAME: "title", "Area": "rich_text", "Owner": "rich_text", "Status": "select"}
PAGE_PATH = re.compile(r"/v1/pages/([^/]+)$")
MARKDOWN_PATH = re.compile(r"/v1/pages/([^/]+)/markdown$")
BLOCK_PATH = re.compile(r"/v1/blocks/([^/]+)$")
DATABASE_PATH = re.compile(r"/v1/databases/([^/]+)$")
DATA_SOURCE_PATH = re.compile(r"/v1/data_sources/([^/]+)$")
TASK_PATH = re.compile(r"/v1/async_tasks/([^/]+)$")
UUID_PATHS = (PAGE_PATH, MARKDOWN_PATH, BLOCK_PATH, DATABASE_PATH)
FENCE = re.compile(r"`{3,}|\$\$")


def dashed(page_id: str) -> str:
    plain = notion_page_id(page_id) or page_id
    return f"{plain[:8]}-{plain[8:12]}-{plain[12:16]}-{plain[16:20]}-{plain[20:]}"


def numbered_id(number: int) -> str:
    return f"{number:08x}-0000-4000-8000-{number:012x}"


def as_notion_stores(markdown: str) -> str:
    stored: list[str] = []
    closer: str | None = None
    fence_indent = ""
    in_table = False
    for line in markdown.split("\n"):
        stripped = line.strip()
        if closer is not None:
            if stripped == closer:
                closer = None
            stored.append(line.removeprefix(fence_indent))
            continue
        if not stripped:
            continue
        if in_table or stripped.startswith("<table ") or stripped == "<table>":
            in_table = stripped != "</table>"
            depth = len(line) - len(line.lstrip("\t"))
            stored.append("  " * depth + stripped)
            continue
        opener = FENCE.match(stripped)
        if opener is not None:
            closer = opener.group(0)
            fence_indent = line[: len(line) - len(line.lstrip())]
        stored.append(line)
    return "\n".join(stored)


def _rich_text(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "plain_text": text, "text": {"content": text}}] if text else []


def _text_of(rich_text: list[dict[str, Any]]) -> str:
    return "".join(piece["text"]["content"] for piece in rich_text)


@dataclass
class StoredPage:
    page_id: str
    properties: dict[str, tuple[str, Any]]
    markdown: str
    last_edited_time: datetime
    last_edited_by: str
    in_trash: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "object": "page",
            "id": dashed(self.page_id),
            "last_edited_time": self.last_edited_time.isoformat().replace("+00:00", ".000Z"),
            "last_edited_by": {"object": "user", "id": self.last_edited_by},
            "in_trash": self.in_trash,
            "properties": {
                name: _property_json(kind, value) for name, (kind, value) in self.properties.items()
            },
        }

    @property
    def title(self) -> str:
        return next(str(value) for kind, value in self.properties.values() if kind == "title")


def _property_json(kind: str, value: Any) -> dict[str, Any]:
    if kind in ("title", "rich_text"):
        return {"id": kind, "type": kind, kind: _rich_text(value or "")}
    if kind == "select":
        option = None if value is None else {"id": "option", "name": value, "color": "default"}
        return {"id": "select", "type": "select", "select": option}
    return {"id": kind, "type": kind, kind: value}


def _property_from_request(kind: str, sent: dict[str, Any]) -> Any:
    if kind in ("title", "rich_text"):
        return _text_of(sent[kind])
    if kind == "select":
        return None if sent["select"] is None else sent["select"]["name"]
    return sent[kind]


@dataclass(frozen=True)
class Scripted:
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict[str, str])
    method: str | None = None
    path_prefix: str = "/"

    def answers(self, request: httpx2.Request) -> bool:
        method_matches = self.method is None or self.method == request.method
        return method_matches and request.url.path.startswith(self.path_prefix)


@dataclass
class InMemoryNotion:
    pages: dict[str, StoredPage] = field(default_factory=dict[str, StoredPage])
    databases: dict[str, dict[str, str]] = field(default_factory=dict[str, dict[str, str]])
    tasks: dict[str, Any] = field(default_factory=dict[str, Any])
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    scripted: list[Scripted] = field(default_factory=list[Scripted])
    answers_writes_later: bool = True
    accepted_token: str = "access-token"
    _edits: int = 0
    _made: int = 0

    def api(self) -> NotionApi:
        return NotionApi(_Tokens(self.accepted_token), transport=self.mock(), sleep=lambda _: None)

    def transport(self) -> NotionTransport:
        return NotionTransport(self.api())

    def mock(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def add_database(self, database_id: str, schema: dict[str, str] | None = None) -> None:
        self.databases[notion_page_id(database_id) or database_id] = dict(schema or DATABASE_SCHEMA)

    def add_page(
        self,
        page_id: str,
        title: str,
        markdown: str = "",
        properties: dict[str, tuple[str, Any]] | None = None,
    ) -> str:
        key = notion_page_id(page_id) or page_id
        self.pages[key] = StoredPage(
            key,
            {**(properties or {TITLE_NAME: ("title", title)})},
            as_notion_stores(markdown),
            self._edit_time(),
            PERSON_ID,
        )
        return key

    def add_row(self, page_id: str, title: str, database_id: str, **values: Any) -> str:
        schema = self.databases[notion_page_id(database_id) or database_id]
        properties = {
            name: (kind, title if kind == "title" else values.get(name)) for name, kind in schema.items()
        }
        return self.add_page(page_id, title, properties=properties)

    def edit_by_hand(self, page_id: str, old: str, new: str) -> None:
        page = self.pages[notion_page_id(page_id) or page_id]
        if page.markdown.count(old) != 1:
            raise AssertionError(f"{old!r} is not on the page once")
        page.markdown = as_notion_stores(page.markdown.replace(old, new))
        self._touch(page, PERSON_ID)

    def comment_on(self, page_id: str, text: str) -> None:
        self.edit_by_hand(page_id, text, f'<span discussion-urls="discussion://comment-1">{text}</span>')

    def click_below_the_last_block(self, page_id: str) -> None:
        page = self.pages[notion_page_id(page_id) or page_id]
        page.markdown += "\n<empty-block/>"
        self._touch(page, PERSON_ID)

    def set_property_by_hand(self, page_id: str, name: str, value: Any) -> None:
        page = self.pages[notion_page_id(page_id) or page_id]
        kind, _ = page.properties[name]
        page.properties[name] = (kind, value)
        self._touch(page, PERSON_ID)

    def markdown_of(self, page_id: str) -> str:
        return self.pages[notion_page_id(page_id) or page_id].markdown

    def writes(self) -> list[tuple[str, str]]:
        return [(request.method, request.url.path) for request in self.requests if request.method != "GET"]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path == "/v1/oauth/token":
            self.accepted_token = "renewed-access"
            return httpx2.Response(200, json=_token_answer(self.accepted_token))
        if request.headers.get("authorization") != f"Bearer {self.accepted_token}":
            return _error(401, "unauthorized", "API token is invalid.")
        if self.scripted and self.scripted[0].answers(request):
            answer = self.scripted.pop(0)
            return httpx2.Response(answer.status, json=answer.body, headers=answer.headers)
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        return self._route(request.method, request.url.path, body)

    def _route(self, method: str, path: str, body: dict[str, Any]) -> httpx2.Response:
        if (method, path) == ("GET", "/v1/users/me"):
            return httpx2.Response(
                200, json={"object": "user", "id": BOT_ID, "type": "bot", "name": "skaldr"}
            )
        if (method, path) == ("POST", "/v1/pages"):
            return self._create(body)
        for pattern, handler in (
            (MARKDOWN_PATH, self._markdown),
            (PAGE_PATH, self._page),
            (BLOCK_PATH, self._block),
            (DATABASE_PATH, self._database),
            (DATA_SOURCE_PATH, self._data_source),
            (TASK_PATH, self._task),
        ):
            found = pattern.fullmatch(path)
            if found is not None and pattern in UUID_PATHS and notion_page_id(found.group(1)) is None:
                return _error(400, "validation_error", "path.id should be a valid uuid")
            if found is not None:
                return handler(method, found.group(1), body)
        return _error(400, "invalid_request_url", f"no route for {method} {path}")

    def _found(self, page_id: str) -> StoredPage | None:
        return self.pages.get(notion_page_id(page_id) or page_id)

    def _page(self, method: str, page_id: str, body: dict[str, Any]) -> httpx2.Response:
        page = self._found(page_id)
        if page is None:
            return _error(404, "object_not_found", "Could not find page.")
        if method == "GET":
            return httpx2.Response(200, json=page.as_json())
        if "in_trash" in body:
            page.in_trash = bool(body["in_trash"])
        refusal = self._set_properties(page, body.get("properties", {}))
        if refusal is not None:
            return refusal
        self._touch(page, BOT_ID)
        return httpx2.Response(200, json=page.as_json())

    def _set_properties(self, page: StoredPage, sent: dict[str, Any]) -> httpx2.Response | None:
        for name in sent:
            if not self._property_name(page, name):
                return _error(400, "validation_error", f"{name} is not a property that exists.")
        for name, value in sent.items():
            target = self._property_name(page, name)
            kind, _ = page.properties[target]
            page.properties[target] = (kind, _property_from_request(kind, value))
        return None

    def _property_name(self, page: StoredPage, name: str) -> str:
        if name in page.properties:
            return name
        if name == "title":
            return next(key for key, (kind, _) in page.properties.items() if kind == "title")
        return ""

    def _markdown(self, method: str, page_id: str, body: dict[str, Any]) -> httpx2.Response:
        page = self._found(page_id)
        if page is None:
            return _error(404, "object_not_found", "Could not find page.")
        if method == "GET":
            return httpx2.Response(200, json=_markdown_json(page))
        if page.in_trash:
            return _error(400, "validation_error", "Can't edit block that is archived.")
        if body["type"] == "replace_content":
            page.markdown = as_notion_stores(body["replace_content"]["new_str"])
        else:
            updated = page.markdown
            for update in body["update_content"]["content_updates"]:
                matches = updated.count(update["old_str"])
                if matches != 1:
                    found = "No matches found" if matches == 0 else "Multiple matches found"
                    return _error(400, "validation_error", f"{found} for old_str.")
                updated = updated.replace(update["old_str"], update["new_str"])
            page.markdown = as_notion_stores(updated)
        self._touch(page, BOT_ID)
        return self._answer(body, _markdown_json(page))

    def _create(self, body: dict[str, Any]) -> httpx2.Response:
        parent = body["parent"]
        if "data_source_id" in parent:
            schema = self.databases.get(parent["data_source_id"].removeprefix("source-"))
            if schema is None:
                return _error(404, "object_not_found", "Could not find data source.")
            properties = {name: (kind, None) for name, kind in schema.items()}
        else:
            parent_page = self._found(parent["page_id"])
            if parent_page is None or parent_page.in_trash:
                return _error(404, "object_not_found", "Could not find page.")
            properties = {"title": ("title", "")}
        self._made += 1
        page = StoredPage(
            numbered_id(self._made).replace("-", ""),
            properties,
            as_notion_stores(body.get("markdown", "")),
            self._edit_time(),
            BOT_ID,
        )
        refusal = self._set_properties(page, body.get("properties", {}))
        if refusal is not None:
            return refusal
        self.pages[page.page_id] = page
        if "page_id" in parent:
            self._list_child_page(self.pages[notion_page_id(parent["page_id"]) or parent["page_id"]], page)
        return self._answer(body, page.as_json())

    def _list_child_page(self, parent: StoredPage, child: StoredPage) -> None:
        reference = f'<page url="https://www.notion.so/{child.page_id}">{child.title}</page>'
        parent.markdown = as_notion_stores(f"{parent.markdown}\n{reference}")
        self._touch(parent, BOT_ID)

    def _block(self, method: str, block_id: str, _body: dict[str, Any]) -> httpx2.Response:
        key = notion_page_id(block_id) or block_id
        kind = "child_database" if key in self.databases else "child_page" if key in self.pages else None
        if method != "GET" or kind is None:
            return _error(404, "object_not_found", "Could not find block.")
        return httpx2.Response(
            200, json={"object": "block", "id": dashed(key), "type": kind, "in_trash": False}
        )

    def _database(self, _method: str, database_id: str, _body: dict[str, Any]) -> httpx2.Response:
        key = notion_page_id(database_id) or database_id
        if key not in self.databases:
            return _error(404, "object_not_found", "Could not find database.")
        sources = [{"id": f"source-{key}", "name": "Garden"}]
        return httpx2.Response(200, json={"object": "database", "id": dashed(key), "data_sources": sources})

    def _data_source(self, _method: str, data_source_id: str, _body: dict[str, Any]) -> httpx2.Response:
        schema = self.databases.get(data_source_id.removeprefix("source-"))
        if schema is None:
            return _error(404, "object_not_found", "Could not find data source.")
        properties = {name: {"id": name.lower(), "name": name, "type": kind} for name, kind in schema.items()}
        return httpx2.Response(
            200, json={"object": "data_source", "id": data_source_id, "properties": properties}
        )

    def _task(self, _method: str, task_id: str, _body: dict[str, Any]) -> httpx2.Response:
        result = self.tasks.pop(task_id)
        return httpx2.Response(200, json={**_task_json(task_id, "succeeded"), "result": result})

    def _answer(self, body: dict[str, Any], result: dict[str, Any]) -> httpx2.Response:
        if not (body.get("allow_async") and self.answers_writes_later):
            return httpx2.Response(200, json=result)
        task_id = f"task-{len(self.tasks) + len(self.requests)}"
        self.tasks[task_id] = result
        return httpx2.Response(202, json={**_task_json(task_id, "queued"), "poll_after_seconds": 1})

    def _edit_time(self) -> datetime:
        self._edits += 1
        return FIRST_EDIT + timedelta(minutes=self._edits)

    def _touch(self, page: StoredPage, editor: str) -> None:
        page.last_edited_time = self._edit_time()
        page.last_edited_by = editor


@dataclass
class _Tokens:
    access_token: str

    def renew(self) -> None:
        raise AssertionError("the in-memory Notion accepts the token it was given")


def _task_json(task_id: str, status: str) -> dict[str, Any]:
    return {
        "object": "async_task",
        "id": task_id,
        "status": status,
        "status_url": f"https://api.notion.com/v1/async_tasks/{task_id}",
        "created_time": "2026-10-09T12:00:00.000Z",
        "operation": {"surface": "rest", "name": "PATCH /v1/pages/:page_id/markdown"},
    }


def _markdown_json(page: StoredPage) -> dict[str, Any]:
    return {
        "object": "page_markdown",
        "id": dashed(page.page_id),
        "markdown": page.markdown,
        "truncated": False,
        "unknown_block_ids": [],
    }


def _token_answer(access_token: str) -> dict[str, Any]:
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": "renewed-refresh",
        "bot_id": BOT_ID,
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "workspace_name": "Example Workspace",
        "owner": {"type": "user"},
    }


def _error(status: int, code: str, message: str) -> httpx2.Response:
    return httpx2.Response(
        status, json={"object": "error", "status": status, "code": code, "message": message}
    )
