import copy
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import unquote

import httpx2
from pydantic import BaseModel, JsonValue

from skaldr.publish.jira.client import JiraClient
from tests.factories.auth_factory import make_jira_credentials

SITE = "https://example.atlassian.net"
PROJECT = "DEMO"
WRITER: dict[str, JsonValue] = {"accountId": "account-writer", "displayName": "Example Reader"}
EDITOR: dict[str, JsonValue] = {"accountId": "account-editor", "displayName": "Robin Editor"}
TO_DO: dict[str, JsonValue] = {"name": "To Do", "statusCategory": {"key": "new"}}
IN_PROGRESS: dict[str, JsonValue] = {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}
DONE: dict[str, JsonValue] = {"name": "Done", "statusCategory": {"key": "done"}}
CLOSE = "31"
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
History = dict[str, JsonValue]


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


class _CommentBody(BaseModel):
    body: JsonValue


@dataclass(frozen=True)
class Reply:
    status: int
    body: JsonValue = None
    headers: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass
class FakeIssue:
    key: str
    fields: dict[str, JsonValue]
    properties: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    comments: list[JsonValue] = field(default_factory=list[JsonValue])


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
    changelog_page_size: int = 2
    honours_properties_on_create: bool = True
    honours_properties_on_edit: bool = True
    issues: dict[str, FakeIssue] = field(default_factory=dict[str, FakeIssue])
    histories: dict[str, list[History]] = field(default_factory=dict[str, list[History]])
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    queued: list[Reply | httpx2.TransportError] = field(default_factory=list[Reply | httpx2.TransportError])
    sleeps: list[float] = field(default_factory=list[float])
    _issues_made: int = 0
    _history_ids: int = 10_000
    _local_ids: int = 0

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def client(self) -> JiraClient:
        return JiraClient(make_jira_credentials(), transport=self.transport(), sleep=self.sleeps.append)

    def answer_next(self, *replies: Reply | httpx2.TransportError) -> None:
        self.queued.extend(replies)

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

    def log_by_hand(self, key: str, *field_ids: str) -> None:
        self._log(key, EDITOR, [{"field": name, "fieldId": name} for name in field_ids])

    def delete_by_hand(self, key: str) -> None:
        del self.issues[key]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.queued:
            queued = self.queued.pop(0)
            if isinstance(queued, httpx2.TransportError):
                raise queued
            return httpx2.Response(queued.status, json=queued.body, headers=dict(queued.headers))
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
        ]

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
        if description is not None and len(json.dumps(description, separators=(",", ":"))) > 32_767:
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
            name: issue.fields.get(name) if name in _AS_STORED else _decorated(issue.fields.get(name))
            for name in names
            if name
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
        changes = dict(body.fields)
        if "description" in changes:
            changes["description"] = self._stored(changes["description"])
        self._change(issue, changes, WRITER)
        if self.honours_properties_on_edit:
            issue.properties.update({prop.key: prop.value for prop in body.properties})
        return httpx2.Response(204)

    def _change(self, issue: FakeIssue, changes: dict[str, JsonValue], author: dict[str, JsonValue]) -> None:
        items: list[dict[str, JsonValue]] = [
            {
                "field": name,
                "fieldtype": "jira",
                "fieldId": name,
                "fromString": _shown(issue.fields.get(name)),
                "toString": _shown(value),
            }
            for name, value in changes.items()
            if issue.fields.get(name) != value
        ]
        issue.fields.update(changes)
        if items:
            self._log(issue.key, author, items)

    def _log(self, key: str, author: dict[str, JsonValue], items: list[dict[str, JsonValue]]) -> None:
        self._history_ids += 1
        self.histories[key].append(
            {
                "id": str(self._history_ids),
                "author": author,
                "created": f"2026-10-0{1 + len(self.histories[key]) % 9}T10:00:00.000+0000",
                "items": list(items),
            }
        )

    def _changelog(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        start = int(request.url.params.get("startAt", "0"))
        asked = int(request.url.params.get("maxResults", "50"))
        size = min(asked, self.changelog_page_size)
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
            for transition_id, name, to in WORKFLOW[self._current_status(issue)]
        ]
        return httpx2.Response(200, json={"transitions": offered})

    def _transition(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        wanted = _TransitionBody.model_validate_json(request.content).transition.id
        offered = {transition_id: to for transition_id, _, to in WORKFLOW[self._current_status(issue)]}
        if wanted not in offered:
            return httpx2.Response(
                400, json={"errorMessages": [f"Transition id '{wanted}' is not valid for this issue."]}
            )
        self._change(issue, {"status": offered[wanted]}, WRITER)
        return httpx2.Response(204)

    def _comment(self, request: httpx2.Request, key: str) -> httpx2.Response:
        issue = self._issue(key)
        if isinstance(issue, httpx2.Response):
            return issue
        issue.comments.append(_CommentBody.model_validate_json(request.content).body)
        return httpx2.Response(201, json={"id": str(len(issue.comments))})

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
        attrs = node.get("attrs")
        if node.get("type") in ("table", "taskList", "taskItem") and isinstance(attrs, dict):
            self._local_ids += 1
            attrs["localId"] = f"jira-{self._local_ids:04d}"
        for value in node.values():
            self._number_local_ids(value)
