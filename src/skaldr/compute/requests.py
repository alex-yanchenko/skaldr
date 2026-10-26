import json
import math
import shlex
from collections import Counter
from collections.abc import Iterable, Iterator
from http import HTTPStatus
from typing import NamedTuple

from skaldr.models import (
    VARIABLE_TOKEN,
    CaseTone,
    Report,
    Request,
    RequestCapture,
    RequestCase,
    RequestFlow,
    RequestLike,
    RequestQuery,
    RequestResponse,
    RequestVariable,
    Tabs,
    ToneLiteral,
    walk_blocks,
)


def reason_phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""


def status_line(response: RequestResponse) -> str:
    """What the status pill reads. An HTTP/2 response carries no reason phrase, so an omitted one
    falls back to the standard text for the code rather than rendering a bare number."""
    if response.status is None:
        return "no status line"
    return f"{response.status} {response.reason or reason_phrase(response.status)}".strip()


def status_tone(response: RequestResponse) -> CaseTone:
    """The tone a status class carries, so a case with a status never authors its own colour."""
    if response.status is None:
        return "neutral"
    tones: dict[int, CaseTone] = {2: "success", 3: "info", 4: "warning", 5: "danger"}
    return tones.get(response.status // 100, "neutral")


def case_tone(case: RequestCase) -> CaseTone:
    return case.tone or status_tone(case.response)


class ResponseCaption(NamedTuple):
    label: str
    shows_status: bool


def response_caption(core: RequestLike, response: RequestResponse) -> ResponseCaption:
    records_output = core.command is not None or core.query is not None
    return ResponseCaption(
        "Recorded output" if records_output else "Recorded response",
        shows_status=not records_output or response.status is not None,
    )


class RecordedBody(NamedTuple):
    text: str
    is_json: bool


def read_recorded_body(body: str) -> RecordedBody:
    try:
        parsed = json.loads(body)
    except ValueError:
        return RecordedBody(body, is_json=False)
    if "\n" in body.strip() or not isinstance(parsed, dict | list):
        return RecordedBody(body, is_json=True)
    return RecordedBody(json.dumps(parsed, indent=2, ensure_ascii=False), is_json=True)


def resolve_case(text: str, block: RequestLike, case: RequestCase) -> str:
    """`text` with the case axis filled in. The case variable is known when the page is built, so it
    is substituted here; every other `{{name}}` stays for the reader to supply at read time."""
    bindings = block.case_bindings(case)
    if not bindings:
        return text
    return VARIABLE_TOKEN.sub(lambda match: bindings.get(match.group(1), match.group(0)), text)


def reader_variables(owner: Request | RequestFlow) -> list[RequestVariable]:
    cores = [owner] if isinstance(owner, Request) else owner.steps
    bound = {name for core in cores for case in core.cases for name in (case.values or {})}
    open_names = {
        match.group(1)
        for core in cores
        for case in core.cases
        for match in VARIABLE_TOKEN.finditer(sent_text_for(core, case))
    }
    return [
        variable for variable in owner.variables if variable.name not in bound or variable.name in open_names
    ]


def variable_parts(text: str) -> list[tuple[str, str]]:
    """`text` split around its `{{name}}` tokens as (literal, name) pairs, the name empty on the
    trailing literal. The template renders each name as a slot the reader's input writes into."""
    pieces = VARIABLE_TOKEN.split(text)
    return [
        (pieces[index], pieces[index + 1] if index + 1 < len(pieces) else "")
        for index in range(0, len(pieces), 2)
    ]


def request_headers(block: RequestLike, case: RequestCase) -> dict[str, str]:
    """The headers this case sends: its own replacement when it has one, else the request's with any
    `headers_add` layered over the top.

    A name matches case-insensitively, the way it does on the wire, and the request's own spelling is
    the one that renders. Matching by exact string would send `Content-Type` and `content-type` both,
    which is two conflicting values in the command a reader pastes."""
    if case.headers is not None:
        return dict(case.headers)
    if case.headers_add is None:
        return dict(block.headers)
    layered = dict(case.headers_add)
    merged: dict[str, str] = {}
    for name, value in block.headers.items():
        override = next((key for key in layered if key.lower() == name.lower()), None)
        merged[name] = layered.pop(override) if override is not None else value
    merged.update(layered)
    return merged


def request_wire(block: RequestLike, case: RequestCase) -> str:
    """The request as it goes on the wire, with `{{name}}` tokens intact for the reader's slots."""
    call = block.composed_call()
    lines = [f"{call.method} {call.url}"]
    lines += [f"{name}: {value}" for name, value in request_headers(block, case).items()]
    if block.body:
        lines += ["", block.body]
    return resolve_case("\n".join(lines), block, case)


def command_for(core: RequestLike, case: RequestCase) -> str:
    """The command shown under one call, every value written out, so it runs exactly as it is copied:
    the author's own `command` when there is one, else the curl built from the call's fields."""
    verbatim = case.command or core.command
    if verbatim is not None:
        return resolve_case(verbatim, core, case)
    call = core.composed_call()
    parts = [f"curl -i -X {call.method}"]
    parts += [
        f"  -H {shlex.quote(resolve_case(f'{name}: {value}', core, case))}"
        for name, value in request_headers(core, case).items()
    ]
    if core.body:
        parts.append(f"  --data {shlex.quote(resolve_case(core.body, core, case))}")
    parts.append(f"  {shlex.quote(resolve_case(call.url, core, case))}")
    return " \\\n".join(parts)


def query_text_for(query: RequestQuery, core: RequestLike, case: RequestCase) -> str:
    return resolve_case(query.content, core, case)


def sent_text_for(core: RequestLike, case: RequestCase) -> str:
    if core.query is not None:
        return query_text_for(core.query, core, case)
    return command_for(core, case)


CASE_LABEL_CHAR = 7.3
"""Advance width of one monospace character at the strip's 12px, in px. The labels are the only thing
whose width has to be known before the page renders, and a monospace face makes that a count."""

CASE_LABEL_CHROME = 36
"""A label's dot, its margin, and the padding either side of it."""

CASE_STRIP_SLACK = 1.08
"""Margin for a fallback monospace face whose characters run wider than the one measured."""


def strip_width(labels: Iterable[str]) -> int:
    """The width a label strip needs to sit on one line, rounded up to a whole px.

    A strip is honest only while it fits that line: its selected label and the rule beneath form one
    mark pointing at the pane. Wrapped, the rule can only sit under the last row, so a selection in an
    earlier row points at nothing. Below this width the strip becomes a rail instead, which has no row
    to wrap out of."""
    width = sum(len(label) * CASE_LABEL_CHAR + CASE_LABEL_CHROME for label in labels)
    return math.ceil(width * CASE_STRIP_SLACK) + 32


class StripLabel(NamedTuple):
    label: str
    tone: ToneLiteral | None


class Strip(NamedTuple):
    name: str
    labels: tuple[StripLabel, ...]


StripOwner = RequestLike | Tabs


def _strip_owners(report: Report) -> Iterator[tuple[str, StripOwner]]:
    for block in walk_blocks(report.blocks):
        if isinstance(block, Tabs):
            yield "tb", block
        elif isinstance(block, Request):
            yield "rq", block
        elif isinstance(block, RequestFlow):
            for step in block.steps:
                yield "rq", step


def _strip_labels(owner: StripOwner) -> tuple[StripLabel, ...]:
    if isinstance(owner, Tabs):
        return tuple(StripLabel(tab.label, tab.tone) for tab in owner.tabs)
    return tuple(StripLabel(case.label, case_tone(case)) for case in owner.cases)


def strip_registry(report: Report) -> dict[int, Strip]:
    """`id(tabs block, request or step) -> its strip`, in document order.

    One radio group name per strip, numbered rather than derived from a label, because it has to be
    unique across the page and safe in an `id` attribute, and a label is neither."""
    numbered: Counter[str] = Counter()
    strips: dict[int, Strip] = {}
    for prefix, owner in _strip_owners(report):
        strips[id(owner)] = Strip(f"{prefix}{numbered[prefix]}", _strip_labels(owner))
        numbered[prefix] += 1
    return strips


def strip_rules(strips: Iterable[Strip]) -> str:
    """A container query per strip of more than one label, at the width its own labels need.

    A query condition takes a literal rather than a custom property, so the threshold cannot ride on
    the element as a variable and each strip contributes its own rule. The strips are the same ones
    the markup names its radios from, so a rule and the strip it shapes cannot drift apart."""
    return "\n".join(
        rail_rule(strip.name, strip_width(label.label for label in strip.labels))
        for strip in strips
        if len(strip.labels) > 1
    )


def rail_rule(name: str, width: int) -> str:
    return (
        f"@container (width < {width}px){{"
        f".{name}{{grid-template-columns:minmax(9rem,max-content) 1fr; display:grid; "
        f"gap:0 var(--s3)}}"
        f".{name} > .tab-list{{flex-direction:column; flex-wrap:nowrap; border-bottom:0; "
        f"border-inline-end:1px solid var(--line); margin-inline-end:0; "
        f"max-height:18rem; overflow-y:auto; grid-row:1; grid-column:1}}"
        f".{name} > .tab-list > *{{border-radius:var(--r-sm); border:0; text-align:start; "
        f"white-space:normal; overflow:visible; text-overflow:clip}}"
        f".{name} > .tab-pane{{grid-row:1; grid-column:2}}"
        "}"
    )


def produced_names(flow: RequestFlow) -> list[tuple[RequestCapture, int]]:
    """Each capture with the 1-based number of the step that produces it, for the reader's field list."""
    return [(capture, index + 1) for index, step in enumerate(flow.steps) for capture in step.captures]
