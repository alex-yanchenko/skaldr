import html
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx2

from skaldr.publish.slack.api import SlackApi
from skaldr.publish.slack.transport import SlackTransport
from tests.factories.auth_factory import SLACK_USER_TOKEN, slack_auth_answer

WORKSPACE_URL = "https://example-garden.slack.com/"
TEAM_ID = "T0EXAMPLE1"
DASH_BULLET = re.compile(r"^(\s*)- ")
MENTION = re.compile(r"!\[\]\(([@#][A-Z0-9]+)\)")
FENCE = re.compile(r"`{3,}")
SEPARATOR_CELL = re.compile(r":?-{3,}:?")
LIST_ITEM = re.compile(r"(?:\*|\d+\.) ")


class FakeToken:
    @property
    def access_token(self) -> str:
        return SLACK_USER_TOKEN


def _blocks_as_sent(markdown: str) -> list[list[str]]:
    blocks: list[list[str]] = [[]]
    fence: str | None = None
    depth = 0
    for line in markdown.split("\n"):
        stripped = line.strip()
        if fence is None and depth == 0 and line == "":
            blocks.append([])
            continue
        if fence is not None:
            fence = None if stripped == fence else fence
        elif (opening := FENCE.match(stripped)) is not None:
            fence = opening.group(0)
        elif stripped.startswith(":::") and "{" in stripped:
            depth += 1
        elif stripped == ":::":
            depth -= 1
        blocks[-1].append(line)
    return [block for block in blocks if block]


def _stored_row(line: str) -> str:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if all(SEPARATOR_CELL.fullmatch(cell) for cell in cells):
        return "|" + "|".join("  ---  " for _ in cells) + "|"
    return "|" + "|".join(cells) + "|"


def _stored_block(lines: list[str]) -> str:
    if "\n".join(lines).strip() == "&nbsp;":
        return " "
    stored: list[str] = []
    in_code = False
    for line in lines:
        if FENCE.match(line.strip()):
            in_code = not in_code
            stored.append(line)
        elif in_code:
            stored.append(line)
        elif line.startswith("|"):
            stored.append(_stored_row(line))
        else:
            stored.append(MENTION.sub(r"<\1>", DASH_BULLET.sub(r"\1* ", line)))
    return "\n".join(stored)


def as_slack_stores(markdown: str) -> list[str]:
    return [_stored_block(lines) for lines in _blocks_as_sent(markdown)]


def _shown(block: str) -> str:
    return f"{block}\n" if block.startswith("|") else block


def _list_html(section_id: str, block: str) -> str:
    items = "".join(
        f"<li id='{section_id}-{index}'>{html.escape(line[2:])}</li>"
        for index, line in enumerate(block.split("\n"))
    )
    return f"<ul id='{section_id}'>{items}</ul>"


def _table_html(section_id: str, block: str) -> str:
    rows = [line.strip("|").split("|") for line in block.split("\n") if line and "---" not in line]
    shown = "".join(
        "<tr>" + "".join(f"<td>{html.escape(cell.strip())}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table id='{section_id}'><tbody>{shown}</tbody></table>"


def _element(section_id: str, block: str) -> str:
    if block == "---":
        return f"<hr id='{section_id}'>"
    if LIST_ITEM.match(block):
        return _list_html(section_id, block)
    if block.startswith("|"):
        return _table_html(section_id, block)
    return f"<p id='{section_id}'>{html.escape(block)}</p>"


@dataclass
class StoredCanvas:
    title: str
    blocks: list[str]
    generation: int = 0

    def ids(self, canvas_id: str) -> list[str]:
        return [f"temp:C:{canvas_id}-{self.generation}-{index}" for index in range(len(self.blocks) + 1)]

    def markdown(self) -> str:
        return "\n\n".join([f"# {self.title}", *map(_shown, self.blocks)]) + "\n"

    def html(self, canvas_id: str, *, omits_the_last: bool = False) -> str:
        title_id, *block_ids = self.ids(canvas_id)
        elements = [
            _element(section_id, block) for section_id, block in zip(block_ids, self.blocks, strict=True)
        ]
        shown = elements[:-1] if omits_the_last else elements
        return f"<h1 id='{title_id}'>{html.escape(self.title)}</h1>{''.join(shown)}"


def form_fields(request: httpx2.Request) -> dict[str, Any]:
    fields = {name: values[0] for name, values in parse_qs(request.content.decode()).items()}
    return {
        name: json.loads(value) if value.startswith(("[", "{")) else value for name, value in fields.items()
    }


def _ok(**fields: Any) -> httpx2.Response:
    return httpx2.Response(200, json={"ok": True, **fields})


def _refused(error: str) -> httpx2.Response:
    return httpx2.Response(200, json={"ok": False, "error": error})


@dataclass
class _Failure:
    method: str
    error: str
    times: int
    passed_first: int
    operation: str | None

    def matches(self, method: str, form: dict[str, Any]) -> bool:
        if method != self.method:
            return False
        return self.operation is None or form["changes"][0]["operation"] == self.operation


@dataclass
class InMemorySlack:
    canvases: dict[str, StoredCanvas] = field(default_factory=dict[str, StoredCanvas])
    messages: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    readers: list[tuple[str, str, list[str]]] = field(default_factory=list[tuple[str, str, list[str]]])
    warnings: list[str] = field(default_factory=list[str])
    requests: list[tuple[str, dict[str, Any]]] = field(default_factory=list[tuple[str, dict[str, Any]]])
    slept: list[float] = field(default_factory=list[float])
    failures: list[_Failure] = field(default_factory=list[_Failure])
    html_lists_one_section_less_after: int | None = None
    retry_after_next: str | None = None
    made: int = 0
    html_reads: int = 0

    def api(self) -> SlackApi:
        return SlackApi(FakeToken(), transport=httpx2.MockTransport(self.handle), sleep=self.slept.append)

    def transport(self) -> SlackTransport:
        return SlackTransport(self.api(), warn=self.warnings.append)

    def mock(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def add_canvas(self, title: str, markdown: str = "") -> str:
        self.made += 1
        canvas_id = f"F{self.made:09d}"
        self.canvases[canvas_id] = StoredCanvas(title, as_slack_stores(markdown))
        return canvas_id

    def edit_by_hand(self, canvas_id: str, old: str, new: str) -> None:
        canvas = self.canvases[canvas_id]
        canvas.blocks = [new if block == old else block for block in canvas.blocks]
        canvas.generation += 1

    def add_block_by_hand(self, canvas_id: str, at: int, text: str) -> None:
        canvas = self.canvases[canvas_id]
        canvas.blocks.insert(at, text)
        canvas.generation += 1

    def rename_by_hand(self, canvas_id: str, title: str) -> None:
        self.canvases[canvas_id].title = title

    def markdown_of(self, canvas_id: str) -> str:
        return self.canvases[canvas_id].markdown()

    def fail_next(
        self, method: str, error: str, *, times: int = 1, after: int = 0, operation: str | None = None
    ) -> None:
        self.failures.append(_Failure(method, error, times, after, operation))

    def answer_too_many_requests_next(self, *, retry_after: str) -> None:
        self.retry_after_next = retry_after

    def writes(self) -> list[tuple[str, str]]:
        return [
            (method, str(form["changes"][0]["operation"]) if method == "canvases.edit" else "")
            for method, form in self.requests
            if method in ("canvases.create", "canvases.edit", "canvases.access.set", "chat.postMessage")
        ]

    def calls(self) -> list[str]:
        return [
            f"{method} {form.get('content_type', '')}".strip() if method == "canvases.getContent" else method
            for method, form in self.requests
        ]

    def forget_requests(self) -> None:
        self.requests.clear()

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        method = request.url.path.removeprefix("/api/")
        form = form_fields(request)
        self.requests.append((method, form))
        if request.headers.get("authorization") != f"Bearer {SLACK_USER_TOKEN}":
            return _refused("invalid_auth")
        if self.retry_after_next is not None:
            retry_after, self.retry_after_next = self.retry_after_next, None
            return httpx2.Response(
                429, json={"ok": False, "error": "ratelimited"}, headers={"Retry-After": retry_after}
            )
        failure = next((failure for failure in self.failures if failure.matches(method, form)), None)
        if failure is not None and failure.passed_first > 0:
            failure.passed_first -= 1
        elif failure is not None:
            failure.times -= 1
            if failure.times == 0:
                self.failures.remove(failure)
            return _refused(failure.error)
        return self._route(method, form)

    def _route(self, method: str, form: dict[str, Any]) -> httpx2.Response:
        if method == "auth.test":
            return httpx2.Response(200, json=slack_auth_answer(url=WORKSPACE_URL, team_id=TEAM_ID))
        if method == "chat.postMessage":
            self.messages.append((form["channel"], form["text"]))
            return _ok(ts="1700000000.000100")
        if method == "canvases.create":
            return _ok(canvas_id=self.add_canvas(form["title"], form["document_content"]["markdown"]))
        canvas = self.canvases.get(form["canvas_id"])
        if canvas is None:
            return _refused("canvas_not_found")
        if method == "canvases.access.set":
            self.readers.append((form["canvas_id"], form["access_level"], form["channel_ids"]))
            return _ok()
        if method == "canvases.getContent" and form["content_type"] == "markdown":
            return _ok(content=canvas.markdown())
        if method == "canvases.getContent":
            return _ok(content=self._html(form["canvas_id"], canvas))
        if method == "canvases.edit":
            return self._edit(form["canvas_id"], canvas, form["changes"])
        return _refused("unknown_method")

    def _html(self, canvas_id: str, canvas: StoredCanvas) -> str:
        omits = self.html_lists_one_section_less_after
        self.html_reads += 1
        return canvas.html(canvas_id, omits_the_last=omits is not None and self.html_reads > omits)

    def _edit(self, canvas_id: str, canvas: StoredCanvas, changes: list[dict[str, Any]]) -> httpx2.Response:
        if len(changes) != 1:
            return _refused("invalid_arguments")
        change = changes[0]
        operation = change["operation"]
        added = as_slack_stores(change.get("document_content", {}).get("markdown", ""))
        ids = canvas.ids(canvas_id)
        if "section_id" in change and change["section_id"] not in ids:
            return _refused("canvas_section_not_found")
        at = ids.index(change["section_id"]) - 1 if "section_id" in change else None
        if operation == "insert_at_start":
            canvas.blocks = [*added, *canvas.blocks]
        elif operation == "insert_at_end":
            canvas.blocks = [*canvas.blocks, *added]
        elif operation == "insert_after" and at is not None:
            canvas.blocks[at + 1 : at + 1] = added
        elif operation == "delete" and at is not None and at >= 0:
            del canvas.blocks[at]
        elif operation == "replace" and at is None:
            canvas.blocks = added
        elif operation == "replace" and at is not None and at >= 0:
            canvas.blocks[at : at + 1] = added
        elif operation == "rename":
            canvas.title = change["title_content"]["markdown"]
        else:
            return _refused("invalid_change")
        canvas.generation += 1
        return _ok()
