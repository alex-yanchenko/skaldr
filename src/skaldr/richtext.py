from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Final, Literal, Protocol, TypeVar

from markdown_it.token import Token
from typing_extensions import assert_never

from skaldr.errors import ReportError
from skaldr.models import Person, ToneLiteral
from skaldr.richtext_syntax import (
    ANCHOR_PREFIX,
    CITATION,
    CODE_INLINE,
    EM_OPEN,
    INLINE_MATH,
    LINK_OPEN,
    MAX_NESTING,
    PLACEHOLDER,
    SPAN_TONES,
    STRIKE_OPEN,
    STRONG_OPEN,
    SUBSCRIPT,
    SUPERSCRIPT,
    TINT_OPEN,
    UNDERLINE_OPEN,
    SpanTones,
    inline_tokens,
    nested_too_deep,
)
from skaldr.typed_links import (
    DATE_SCHEME,
    DOC_SCHEME,
    JIRA_SCHEME,
    USER_SCHEME,
    date_target,
    document_target,
    issue_key,
    person_key,
)

MarkerStyle = Literal["bold", "italic", "strike"]
StyleName = Literal[MarkerStyle, "underline"]
ScriptPosition = Literal["subscript", "superscript"]
SCRIPT_HTML_TAG: Final[Mapping[ScriptPosition, str]] = {"subscript": "sub", "superscript": "sup"}
Written = TypeVar("Written")


@dataclass(frozen=True)
class Plain:
    text: str


@dataclass(frozen=True)
class Code:
    text: str


@dataclass(frozen=True)
class Link:
    label: "Rich"
    url: str


@dataclass(frozen=True)
class AnchorLink:
    label: "Rich"
    anchor: str


@dataclass(frozen=True)
class DateMention:
    label: "Rich"
    start: date
    end: date | None


@dataclass(frozen=True)
class PersonMention:
    label: "Rich"
    key: str
    person: Person


@dataclass(frozen=True)
class IssueLink:
    label: "Rich"
    key: str
    url: str | None


@dataclass(frozen=True)
class DocumentLink:
    label: "Rich"
    doc_id: str
    section: str | None


@dataclass(frozen=True)
class Citation:
    key: str
    number: int
    url: str | None = None


@dataclass(frozen=True)
class Placeholder:
    name: str


@dataclass(frozen=True)
class Styled:
    style: StyleName
    runs: "Rich"


@dataclass(frozen=True)
class ScriptText:
    position: ScriptPosition
    text: str


@dataclass(frozen=True)
class Tinted:
    tone: ToneLiteral | None
    background: ToneLiteral | None
    runs: "Rich"


@dataclass(frozen=True)
class InlineMath:
    expression: str


Run = (
    Plain
    | Code
    | Link
    | AnchorLink
    | DateMention
    | PersonMention
    | IssueLink
    | DocumentLink
    | Citation
    | Placeholder
    | Styled
    | ScriptText
    | Tinted
    | InlineMath
)
Rich = tuple[Run, ...]

_STYLE_OPENERS: Final[Mapping[str, StyleName]] = {
    STRONG_OPEN: "bold",
    EM_OPEN: "italic",
    STRIKE_OPEN: "strike",
    UNDERLINE_OPEN: "underline",
}
_SCRIPT_TOKENS: Final[Mapping[str, ScriptPosition]] = {SUBSCRIPT: "subscript", SUPERSCRIPT: "superscript"}


@dataclass(frozen=True)
class RichContext:
    reference_numbers: Mapping[str, int] | None = None
    reference_urls: Mapping[str, str | None] = field(default_factory=dict[str, "str | None"])
    anchor_ids: frozenset[str] | None = None
    people: Mapping[str, Person] = field(default_factory=dict[str, Person])
    jira_site: str | None = None


def parse_rich(text: str, context: RichContext | None = None) -> Rich:
    rules = context if context is not None else RichContext()
    runs, _ = _runs_until_close(inline_tokens(text, rules.reference_numbers or {}), 0, rules, 0)
    return runs


def _runs_until_close(
    tokens: Sequence[Token], start: int, rules: RichContext, depth: int
) -> tuple[Rich, int]:
    runs: list[Run] = []
    index = start
    while index < len(tokens) and tokens[index].nesting != -1:
        token = tokens[index]
        if token.nesting == 1:
            if depth == MAX_NESTING:
                raise nested_too_deep()
            inner, index = _runs_until_close(tokens, index + 1, rules, depth + 1)
            runs.extend(_wrapped_runs(token, inner, rules))
        else:
            runs.append(_leaf_run(token, rules))
        index += 1
    return _merged(runs), index


def _wrapped_runs(opener: Token, inner: Rich, rules: RichContext) -> Rich:
    if opener.type == LINK_OPEN:
        return _link_runs(str(opener.attrs["href"]), inner, rules)
    if opener.type == TINT_OPEN:
        tones: SpanTones = opener.meta[SPAN_TONES]
        return (Tinted(tones.tone, tones.background, inner),)
    return (Styled(_STYLE_OPENERS[opener.type], inner),)


def _typed_link_run(url: str, label: Rich, rules: RichContext) -> Run | None:
    if url.startswith(DATE_SCHEME):
        target = date_target(url)
        return DateMention(label, target.start, target.end)
    if url.startswith(USER_SCHEME):
        key = person_key(url)
        if key not in rules.people:
            raise ReportError(f"rich text links to unknown person '{key}': declare it under meta.people")
        return PersonMention(label, key, rules.people[key])
    if url.startswith(JIRA_SCHEME):
        key = issue_key(url)
        return IssueLink(label, key, f"{rules.jira_site}/browse/{key}" if rules.jira_site else None)
    if url.startswith(DOC_SCHEME):
        target = document_target(url)
        return DocumentLink(label, target.doc_id, target.section)
    return None


def _link_runs(url: str, label: Rich, rules: RichContext) -> Rich:
    typed = _typed_link_run(url, label, rules)
    if typed is not None:
        return (typed,)
    if not url.startswith(ANCHOR_PREFIX):
        return (Link(label, url),)
    if rules.anchor_ids is None:
        return (Plain("["), *label, Plain(f"]({url})"))
    if url.removeprefix(ANCHOR_PREFIX) not in rules.anchor_ids:
        raise ReportError(f"rich text links to unknown anchor '{url}': no heading or section has that id")
    return (AnchorLink(label, url.removeprefix(ANCHOR_PREFIX)),)


def _leaf_run(token: Token, rules: RichContext) -> Run:
    if token.type == CODE_INLINE:
        return Code(token.content)
    if token.type == PLACEHOLDER:
        return Placeholder(token.content)
    if token.type == CITATION:
        numbers = rules.reference_numbers or {}
        return Citation(token.content, numbers[token.content], rules.reference_urls.get(token.content))
    if token.type == INLINE_MATH:
        return InlineMath(token.content)
    if token.type in _SCRIPT_TOKENS:
        return ScriptText(_SCRIPT_TOKENS[token.type], token.content)
    return Plain(token.content)


def _merged(runs: Iterable[Run]) -> Rich:
    merged: list[Run] = []
    for run in runs:
        if isinstance(run, Plain) and not run.text:
            continue
        previous = merged[-1] if merged else None
        if isinstance(run, Plain) and isinstance(previous, Plain):
            merged[-1] = Plain(previous.text + run.text)
        else:
            merged.append(run)
    return tuple(merged)


class RunWriter(Protocol[Written]):
    def concat(self, parts: Sequence[Written], /) -> Written: ...

    def text(self, text: str, /) -> Written: ...

    def code(self, text: str, /) -> Written: ...

    def link(self, label: Written, url: str, /) -> Written: ...

    def anchor_link(self, label: Written, anchor: str, /) -> Written: ...

    def date_mention(self, label: Written, start: date, end: date | None, /) -> Written: ...

    def person_mention(self, label: Written, key: str, person: Person, /) -> Written: ...

    def issue_link(self, label: Written, key: str, url: str | None, /) -> Written: ...

    def document_link(self, label: Written, doc_id: str, section: str | None, /) -> Written: ...

    def citation(self, run: Citation, /) -> Written: ...

    def placeholder(self, name: str, /) -> Written: ...

    def styled(self, style: StyleName, inner: Written, /) -> Written: ...

    def script(self, position: ScriptPosition, text: str, /) -> Written: ...

    def tinted(
        self, tone: ToneLiteral | None, background: ToneLiteral | None, inner: Written, /
    ) -> Written: ...

    def math(self, expression: str, /) -> Written: ...


class TextRunWriter:
    def concat(self, parts: Sequence[str], /) -> str:
        return "".join(parts)


def write_run(run: Run, writer: RunWriter[Written]) -> Written:
    match run:
        case Plain():
            return writer.text(run.text)
        case Code():
            return writer.code(run.text)
        case Link():
            return writer.link(write_runs(run.label, writer), run.url)
        case AnchorLink():
            return writer.anchor_link(write_runs(run.label, writer), run.anchor)
        case DateMention():
            return writer.date_mention(write_runs(run.label, writer), run.start, run.end)
        case PersonMention():
            return writer.person_mention(write_runs(run.label, writer), run.key, run.person)
        case IssueLink():
            return writer.issue_link(write_runs(run.label, writer), run.key, run.url)
        case DocumentLink():
            return writer.document_link(write_runs(run.label, writer), run.doc_id, run.section)
        case Citation():
            return writer.citation(run)
        case Placeholder():
            return writer.placeholder(run.name)
        case Styled():
            return writer.styled(run.style, write_runs(run.runs, writer))
        case ScriptText():
            return writer.script(run.position, run.text)
        case Tinted():
            return writer.tinted(run.tone, run.background, write_runs(run.runs, writer))
        case InlineMath():
            return writer.math(run.expression)
        case _:
            assert_never(run)


def write_runs(runs: Rich, writer: RunWriter[Written]) -> Written:
    return writer.concat([write_run(run, writer) for run in runs])


class VisibleText(TextRunWriter):
    def text(self, text: str, /) -> str:
        return text

    def code(self, text: str, /) -> str:
        return text

    def link(self, label: str, _url: str, /) -> str:
        return label

    def anchor_link(self, label: str, _anchor: str, /) -> str:
        return label

    def date_mention(self, label: str, _start: date, _end: date | None, /) -> str:
        return label

    def person_mention(self, label: str, _key: str, _person: Person, /) -> str:
        return label

    def issue_link(self, label: str, _key: str, _url: str | None, /) -> str:
        return label

    def document_link(self, label: str, _doc_id: str, _section: str | None, /) -> str:
        return label

    def citation(self, run: Citation, /) -> str:
        return f"[{run.number}]"

    def placeholder(self, name: str, /) -> str:
        return name

    def styled(self, _style: StyleName, inner: str, /) -> str:
        return inner

    def script(self, _position: ScriptPosition, text: str, /) -> str:
        return text

    def tinted(self, _tone: ToneLiteral | None, _background: ToneLiteral | None, inner: str, /) -> str:
        return inner

    def math(self, expression: str, /) -> str:
        return expression


def visible_text(runs: Rich) -> str:
    return write_runs(runs, VisibleText())
