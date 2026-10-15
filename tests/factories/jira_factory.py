import copy
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import unquote

import httpx2
from pydantic import BaseModel, Field, JsonValue

from skaldr.publish.jira.client import JiraClient
from tests.factories.auth_factory import basic_auth_header, make_jira_credentials

SITE = "https://example.atlassian.net"
PROJECT = "DEMO"
WRITER: dict[str, JsonValue] = {"accountId": "account-writer", "displayName": "Example Reader"}
EDITOR: dict[str, JsonValue] = {"accountId": "account-editor", "displayName": "Robin Editor"}
TO_DO: dict[str, JsonValue] = {"name": "To Do", "statusCategory": {"key": "new"}}
IN_PROGRESS: dict[str, JsonValue] = {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}
DONE: dict[str, JsonValue] = {"name": "Done", "statusCategory": {"key": "done"}}
CLOSE = "31"
DONE_RESOLUTION: dict[str, JsonValue] = {"name": "Done"}
RESOLUTION_REQUIRED = "Resolution is required."
SAVED_DEFAULTS: dict[str, dict[str, JsonValue]] = {
    "table": {"isNumberColumnEnabled": False, "layout": "center", "displayMode": "default"},
    "tableHeader": {"colspan": 1, "rowspan": 1},
    "tableCell": {"colspan": 1, "rowspan": 1},
    "orderedList": {"order": 1},
    "mention": {"accessLevel": "", "userType": "DEFAULT"},
}
WORKFLOW: dict[str, list[tuple[str, str, dict[str, JsonValue]]]] = {
    "To Do": [("11", "Start", IN_PROGRESS), (CLOSE, "Close", DONE)],
    "In Progress": [("21", "Stop", TO_DO), (CLOSE, "Close", DONE)],
    "Done": [("41", "Reopen", TO_DO)],
}
NOT_FOUND: dict[str, JsonValue] = {
    "errorMessages": ["Issue does not exist or you do not have permission to see it."],
    "errors": {},
}
_API = "/rest/api/3"
_AS_STORED = frozenset({"description", "status"})
DISPLAY_NAMES = {"customfield_10010": "Story Points"}
REMOTE_LINK_FIELD = "RemoteWorkItemLink"
JSON_MEDIA_TYPE = "application/json"
History = dict[str, JsonValue]
Author = dict[str, JsonValue] | None


def summarised_request(method: str, path: str, body: JsonValue = None) -> dict[str, object]:
    credentials = make_jira_credentials()
    return {
        "method": method,
        "url": f"{SITE}{path}",
        "authorization": basic_auth_header(credentials.email, credentials.api_token),
        "content_type": None if method == "GET" else JSON_MEDIA_TYPE,
        "body": body,
    }


@dataclass(frozen=True)
class PlannedEdit:
    author: Author
    fields: dict[str, JsonValue]
    dated: bool = True


class _EntityProperty(BaseModel):
    key: str
    value: JsonValue


class _IssueBody(BaseModel):
    fields: dict[str, JsonValue] = {}
    properties: list[_EntityProperty] = []


class _TransitionId(BaseModel):
    id: str


class _TransitionBody(BaseModel):
    transition: _TransitionId
    fields: dict[str, JsonValue] = {}


class _CommentBody(BaseModel):
    body: JsonValue


class _RemoteLinkBody(BaseModel):
    global_id: str | None = Field(default=None, alias="globalId")
    linked: dict[str, JsonValue] = Field(alias="object")


@dataclass(frozen=True)
class Reply:
    status: int
    body: JsonValue = None
    headers: Mapping[str, str | bytes] = field(default_factory=dict[str, str | bytes])

    def response(self) -> httpx2.Response:
        raw = [
            (name.encode(), value if isinstance(value, bytes) else value.encode())
            for name, value in self.headers.items()
        ]
        return httpx2.Response(self.status, json=self.body, headers=raw)


Queued = Reply | httpx2.RequestError


class _ClosableMockTransport(httpx2.MockTransport):
    def __init__(
        self, handler: Callable[[httpx2.Request], httpx2.Response], on_close: Callable[[], None]
    ) -> None:
        super().__init__(handler)
        self._on_close = on_close

    def close(self) -> None:
        self._on_close()


@dataclass
class FakeIssue:
    key: str
    fields: dict[str, JsonValue]
    properties: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    comments: list[JsonValue] = field(default_factory=list[JsonValue])
    remote_links: list[dict[str, JsonValue]] = field(default_factory=list[dict[str, JsonValue]])


def _shown(value: JsonValue) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True)


def _decorated(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {"self": f"{SITE}{_API}/thing/1", **value}
    if isinstance(value, list):
        return [_decorated(member) for member in value]
    return value


@dataclass
class FakeJira:
    issue_types: tuple[str, ...] = ("Task", "Story")
    unknown_fields: frozenset[str] = frozenset({"story_points"})
    page_size: int = 2
    honours_properties_on_create: bool = True
    honours_properties_on_edit: bool = True
    close_screen_requires_resolution: bool = False
    fills_in_saved_defaults: bool = False
    issues: dict[str, FakeIssue] = field(default_factory=dict[str, FakeIssue])
    histories: dict[str, list[History]] = field(default_factory=dict[str, list[History]])
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    queued: dict[tuple[str, str], list[Queued]] = field(default_factory=dict[tuple[str, str], list[Queued]])
    sleeps: list[float] = field(default_factory=list[float])
    edits_during_writes: dict[str, list[PlannedEdit]] = field(default_factory=dict[str, list[PlannedEdit]])
    edits_before_writes: dict[str, list[PlannedEdit]] = field(default_factory=dict[str, list[PlannedEdit]])
    adds_to_paragraphs: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    names_in_mentions: dict[str, str] = field(default_factory=dict[str, str])
    closes: int = 0
    _remote_link_id: int = 10_000
    _issues_made: int = 0
    _history_ids: int = 10_000
    _local_ids: int = 0

    def transport(self) -> httpx2.MockTransport:
        return _ClosableMockTransport(self.handle, self._count_a_close)

    def _count_a_close(self) -> None:
        self.closes += 1

    def client(self) -> JiraClient:
        return JiraClient(make_jira_credentials(), transport=self.transport(), sleep=self.sleeps.append)

    def answer_next(self, method: str, path: str, *replies: Queued) -> None:
        self.queued.setdefault((method, path), []).extend(replies)

    def calls(self) -> list[tuple[str, str]]:
        return [(request.method, unquote(request.url.path)) for request in self.requests]

    def forget_requests(self) -> None:
        self.requests.clear()

    def seed(self, key: str, **fields: JsonValue) -> FakeIssue:
        issue = FakeIssue(key, {"status": TO_DO, **fields})
        self.issues[key] = issue
        self.histories.setdefault(key, [])
        return issue

    def edit_by_hand(self, key: str, **fields: JsonValue) -> None:
        self._change(self.issues[key], dict(fields), EDITOR)

    def edit_right_after_the_next_write(
        self, key: str, author: Author = EDITOR, *, dated: bool = True, **fields: JsonValue
    ) -> None:
        self.edits_during_writes.setdefault(key, []).append(PlannedEdit(author, dict(fields), dated))

    def edit_right_before_the_next_write(
        self, key: str, author: Author = EDITOR, *, dated: bool = True, **fields: JsonValue
    ) -> None:
        self.edits_before_writes.setdefault(key, []).append(PlannedEdit(author, dict(fields), dated))

    def _make_planned_edits(self, key: str, planned: list[PlannedEdit]) -> None:
        for edit in planned:
            self._change(self.issues[key], edit.fields, edit.author, dated=edit.dated)

    def _edit_after_writing(self, key: str) -> None:
        self._make_planned_edits(key, self.edits_during_writes.pop(key, []))

    def log_by_hand(self, key: str, *field_ids: str) -> None:
        self._log(key, EDITOR, [{"field": name, "fieldId": name} for name in field_ids])

    def delete_by_hand(self, key: str) -> None:
        del self.issues[key]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.method != "GET" and request.headers.get("content-type") != JSON_MEDIA_TYPE:
            return httpx2.Response(415)
        waiting = self.queued.get((request.method, unquote(request.url.path)))
        if waiting:
            queued = waiting.pop(0)
            if isinstance(queued, httpx2.RequestError):
                raise queued
            return queued.response()
        path = request.url.raw_path.decode().partition("?")[0]
        for pattern, method, answer in self._routes():
            matched = re.fullmatch(pattern, path)
            if matched and request.method == method:
                return answer(request, *(unquote(group) for group in matched.groups()))
        return httpx2.Response(405, json={"errorMessages": [f"no route for {request.method} {path}"]})

    def _routes(
        self,
    ) -> list[tuple[str, str, Callable[..., httpx2.Response]]]:
        issue = rf"{_API}/issue/([^/]+)"
        return [
            (rf"{_API}/myself", "GET", self._myself),
            (rf"{_API}/issue", "POST", self._create),
            (issue, "GET", self._get),
            (issue, "PUT", self._edit),
            (rf"{issue}/changelog", "GET", self._changelog),
            (rf"{issue}/properties/([^/]+)", "GET", self._get_property),
            (rf"{issue}/properties/([^/]+)", "PUT", self._put_property),
            (rf"{issue}/transitions", "GET", self._transitions),
            (rf"{issue}/transitions", "POST", self._transition),
            (rf"{issue}/comment", "POST", self._comment),
            (rf"{issue}/comment", "GET", self._comments),
            (rf"{issue}/remotelink", "GET", self._remote_links),
            (rf"{issue}/remotelink", "POST", self._upsert_remote_link),
            (rf"{issue}/remotelink", "DELETE", self._delete_remote_link),
        ]

    def link_by_hand(self, key: str, global_id: str | None, url: str, title: str) -> None:
        self._remote_link_id += 1
        self.issues[key].remote_links.append(
            {"id": self._remote_link_id, "globalId": global_id, "object": {"url": url, "title": title}}
        )
        self._log_remote_link_change(key, title, EDITOR)

    def _log_remote_link_change(self, key: str, title: JsonValue, author: Author = WRITER) -> None:
        self._log(key, author, [{"field": REMOTE_LINK_FIELD, "fieldtype": "jira", "toString": title}])

    def _remote_links(self, _request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        address = f"{SITE}{_API}/issue/{key}/remotelink"
        links: list[JsonValue] = [{"self": f"{address}/{link['id']}", **link} for link in issue.remote_links]
        return httpx2.Response(200, json=links)

    def _upsert_remote_link(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        body = _RemoteLinkBody.model_validate_json(request.content)
        found = next((link for link in issue.remote_links if link["globalId"] == body.global_id), None)
        sent: dict[str, JsonValue] = {"globalId": body.global_id, "object": body.linked}
        if found is not None:
            found.update(sent)
            return httpx2.Response(200, json={"id": found["id"]})
        self._remote_link_id += 1
        issue.remote_links.append({"id": self._remote_link_id, **sent})
        self._log_remote_link_change(key, body.linked.get("title"))
        return httpx2.Response(201, json={"id": self._remote_link_id})

    def _delete_remote_link(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        global_id = request.url.params.get("globalId")
        kept = [link for link in issue.remote_links if link["globalId"] != global_id]
        if len(kept) == len(issue.remote_links):
            return httpx2.Response(404, json={"errorMessages": ["No remote link with that globalId."]})
        issue.remote_links = kept
        self._log_remote_link_change(key, None)
        return httpx2.Response(204)

    def _myself(self, _request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=WRITER)

    def _refusal(self, fields: Mapping[str, JsonValue]) -> httpx2.Response | None:
        errors: dict[str, JsonValue] = {
            name: f"Field '{name}' cannot be set. It is not on the appropriate screen, or unknown."
            for name in fields
            if name in self.unknown_fields
        }
        issue_type = fields.get("issuetype")
        if isinstance(issue_type, dict) and issue_type.get("name") not in self.issue_types:
            errors["issuetype"] = "Specify a valid issue type"
        description = fields.get("description")
        compact = json.dumps(description, separators=(",", ":"), ensure_ascii=False)
        if description is not None and len(compact) > 32_767:
            errors["description"] = "CONTENT_LIMIT_EXCEEDED"
        if not errors:
            return None
        return httpx2.Response(400, json={"errorMessages": [], "errors": errors})

    def _create(self, request: httpx2.Request) -> httpx2.Response:
        body = _IssueBody.model_validate_json(request.content)
        refused = self._refusal(body.fields)
        if refused is not None:
            return refused
        self._issues_made += 1
        key = f"{PROJECT}-{self._issues_made}"
        fields = {name: value for name, value in body.fields.items() if name != "description"}
        issue = self.seed(key, **fields, description=self._stored(body.fields.get("description")))
        if self.honours_properties_on_create:
            issue.properties = {prop.key: prop.value for prop in body.properties}
        self._edit_after_writing(key)
        return httpx2.Response(201, json={"id": str(10_000 + self._issues_made), "key": key})

    def _issue(self, key: str) -> FakeIssue | httpx2.Response:
        found = self.issues.get(key)
        return httpx2.Response(404, json=NOT_FOUND) if found is None else found

    def _get(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        names = request.url.params.get("fields", "").split(",")
        fields = {
            name: issue.fields[name] if name in _AS_STORED else _decorated(issue.fields[name])
            for name in names
            if name in issue.fields
        }
        issue_id = str(10_000 + int(issue.key.rsplit("-", 1)[1]))
        return httpx2.Response(200, json={"id": issue_id, "key": issue.key, "fields": fields})

    def _edit(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        body = _IssueBody.model_validate_json(request.content)
        refused = self._refusal(body.fields)
        if refused is not None:
            return refused
        self._make_planned_edits(key, self.edits_before_writes.pop(key, []))
        changes = dict(body.fields)
        if "description" in changes:
            changes["description"] = self._stored(changes["description"])
        self._change(issue, changes, WRITER)
        if self.honours_properties_on_edit:
            issue.properties.update({prop.key: prop.value for prop in body.properties})
        self._edit_after_writing(key)
        return httpx2.Response(204)

    def _change(
        self, issue: FakeIssue, changes: dict[str, JsonValue], author: Author, *, dated: bool = True
    ) -> None:
        items: list[dict[str, JsonValue]] = [
            {
                "field": DISPLAY_NAMES.get(name, name),
                "fieldtype": "custom" if name in DISPLAY_NAMES else "jira",
                "fieldId": name,
                "fromString": _shown(issue.fields.get(name)),
                "toString": _shown(value),
            }
            for name, value in changes.items()
            if issue.fields.get(name) != value
        ]
        issue.fields.update(changes)
        if items:
            self._log(issue.key, author, items, dated=dated)

    def _log(
        self, key: str, author: Author, items: list[dict[str, JsonValue]], *, dated: bool = True
    ) -> None:
        self._history_ids += 1
        entry: History = {"id": str(self._history_ids), "items": list(items)}
        if author is not None:
            entry["author"] = author
        if dated:
            entry["created"] = f"2026-10-0{1 + len(self.histories[key]) % 9}T10:00:00.000+0000"
        self.histories[key].append(entry)

    def _changelog(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        start = int(request.url.params.get("startAt", "0"))
        asked = int(request.url.params.get("maxResults", "50"))
        size = min(asked, self.page_size)
        histories: list[JsonValue] = list(self.histories[key])
        page = histories[start : start + size]
        return httpx2.Response(
            200,
            json={
                "startAt": start,
                "maxResults": size,
                "total": len(histories),
                "isLast": start + size >= len(histories),
                "values": page,
            },
        )

    def _get_property(self, _request: httpx2.Request, key: str, name: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        if name not in issue.properties:
            return httpx2.Response(
                404, json={"errorMessages": [f"The property with key '{name}' does not exist."], "errors": {}}
            )
        return httpx2.Response(200, json={"key": name, "value": issue.properties[name]})

    def _put_property(self, request: httpx2.Request, key: str, name: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        created = name not in issue.properties
        issue.properties[name] = json.loads(request.content)
        return httpx2.Response(201 if created else 200)

    def _current_status(self, issue: FakeIssue) -> str:
        status = issue.fields["status"]
        if not isinstance(status, dict) or not isinstance(status["name"], str):
            raise TypeError(f"{issue.key} has no status")
        return status["name"]

    def _transitions(self, _request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        offered: list[JsonValue] = [
            {"id": transition_id, "name": name, "to": to}
            for transition_id, name, to in WORKFLOW.get(self._current_status(issue), [])
        ]
        return httpx2.Response(200, json={"transitions": offered})

    def _transition(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        body = _TransitionBody.model_validate_json(request.content)
        wanted = body.transition.id
        offered = {
            transition_id: to for transition_id, _, to in WORKFLOW.get(self._current_status(issue), [])
        }
        if wanted not in offered:
            return httpx2.Response(
                400, json={"errorMessages": [f"Transition id '{wanted}' is not valid for this issue."]}
            )
        closing = wanted == CLOSE
        if closing and self.close_screen_requires_resolution and "resolution" not in body.fields:
            return httpx2.Response(
                400, json={"errorMessages": [], "errors": {"resolution": RESOLUTION_REQUIRED}}
            )
        resolution = body.fields.get("resolution", DONE_RESOLUTION) if closing else None
        self._change(issue, {"status": offered[wanted], "resolution": resolution}, WRITER)
        return httpx2.Response(204)

    def _comment(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        issue.comments.append(_CommentBody.model_validate_json(request.content).body)
        return httpx2.Response(201, json={"id": str(len(issue.comments))})

    def _comments(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        start = int(request.url.params.get("startAt", "0"))
        size = min(int(request.url.params.get("maxResults", "50")), self.page_size)
        comments: list[JsonValue] = [
            {"id": str(number), "body": body} for number, body in enumerate(issue.comments, start=1)
        ]
        return httpx2.Response(
            200,
            json={
                "startAt": start,
                "maxResults": size,
                "total": len(comments),
                "comments": comments[start : start + size],
            },
        )

    def _stored(self, description: JsonValue) -> JsonValue:
        stored = copy.deepcopy(description)
        self._number_local_ids(stored)
        return stored

    def _number_local_ids(self, node: JsonValue) -> None:
        if isinstance(node, list):
            for member in node:
                self._number_local_ids(member)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "paragraph" and self.adds_to_paragraphs:
            node["attrs"] = dict(self.adds_to_paragraphs)
        node_type = node.get("type")
        if self.fills_in_saved_defaults and isinstance(node_type, str) and node_type in SAVED_DEFAULTS:
            filled = node.get("attrs")
            node["attrs"] = {**SAVED_DEFAULTS[node_type], **(filled if isinstance(filled, dict) else {})}
        attrs = node.get("attrs")
        mentioned = attrs.get("id") if node.get("type") == "mention" and isinstance(attrs, dict) else None
        if isinstance(attrs, dict) and isinstance(mentioned, str) and mentioned in self.names_in_mentions:
            attrs["accessLevel"] = ""
            attrs["text"] = f"@{self.names_in_mentions[mentioned]}"
        if node.get("type") in ("table", "taskList", "taskItem") and isinstance(attrs, dict):
            self._local_ids += 1
            attrs["localId"] = f"jira-{self._local_ids:04d}"
        for value in node.values():
            self._number_local_ids(value)
