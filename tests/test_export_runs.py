from collections.abc import Sequence
from datetime import date

from skaldr.export.runs import (
    Break,
    Chip,
    ExportRich,
    ExportRunWriter,
    Gauge,
    Mark,
    StatusMark,
    mark_name,
    write_export_runs,
)
from skaldr.models import Person, ToneLiteral
from skaldr.richtext import (
    AnchorLink,
    Citation,
    Code,
    InlineMath,
    Link,
    Placeholder,
    Plain,
    ScriptPosition,
    ScriptText,
    Styled,
    StyleName,
    Tinted,
    write_runs,
)

MarkedNode = tuple[str, str, tuple[str, ...]]
MarkedNodes = tuple[MarkedNode, ...]


def _leaf(kind: str, text: str) -> MarkedNodes:
    return ((kind, text, ()),)


def _with_mark(mark: str, inner: MarkedNodes) -> MarkedNodes:
    return tuple((kind, text, (*marks, mark)) for kind, text, marks in inner)


class _MarkedNodeRuns:
    def concat(self, parts: Sequence[MarkedNodes], /) -> MarkedNodes:
        return tuple(node for part in parts for node in part)

    def text(self, text: str, /) -> MarkedNodes:
        return _leaf("text", text)

    def code(self, text: str, /) -> MarkedNodes:
        return _with_mark("code", _leaf("text", text))

    def link(self, label: MarkedNodes, url: str, /) -> MarkedNodes:
        return _with_mark(f"link={url}", label)

    def anchor_link(self, label: MarkedNodes, anchor: str, /) -> MarkedNodes:
        return _with_mark(f"anchor={anchor}", label)

    def date_mention(self, label: MarkedNodes, start: date, end: date | None, /) -> MarkedNodes:
        return _with_mark(f"date={start}/{end}", label)

    def person_mention(self, label: MarkedNodes, key: str, _person: Person, /) -> MarkedNodes:
        return _with_mark(f"person={key}", label)

    def issue_link(self, label: MarkedNodes, key: str, _url: str | None, /) -> MarkedNodes:
        return _with_mark(f"issue={key}", label)

    def document_link(self, label: MarkedNodes, doc_id: str, _section: str | None, /) -> MarkedNodes:
        return _with_mark(f"document={doc_id}", label)

    def citation(self, run: Citation, /) -> MarkedNodes:
        return _with_mark(f"citation={run.key}", _leaf("text", f"[{run.number}]"))

    def placeholder(self, name: str, /) -> MarkedNodes:
        return _leaf("placeholder", name)

    def styled(self, style: StyleName, inner: MarkedNodes, /) -> MarkedNodes:
        return _with_mark(style, inner)

    def script(self, position: ScriptPosition, text: str, /) -> MarkedNodes:
        return _with_mark(position, _leaf("text", text))

    def tinted(
        self, tone: ToneLiteral | None, background: ToneLiteral | None, inner: MarkedNodes, /
    ) -> MarkedNodes:
        return _with_mark(f"tint={tone}/{background}", inner)

    def math(self, expression: str, /) -> MarkedNodes:
        return _leaf("math", expression)

    def chip(self, run: Chip, /) -> MarkedNodes:
        return _with_mark(run.tone, _leaf("status", run.label))

    def line_break(self) -> MarkedNodes:
        return _leaf("hardBreak", "")

    def mark(self, run: Mark, /) -> MarkedNodes:
        return _leaf("status", mark_name(run))

    def gauge(self, run: Gauge, /) -> MarkedNodes:
        return _leaf("gauge", f"{run.value}/{run.maximum}")


def _structured_writer() -> ExportRunWriter[MarkedNodes]:
    return _MarkedNodeRuns()


def test_a_run_writer_can_build_marked_nodes_where_each_wrapper_marks_the_nodes_inside_it() -> None:
    runs = (
        Plain("a "),
        Styled("bold", (Plain("b "), Link((Code("c"), Plain(" d")), "https://example.com/x"))),
        AnchorLink((Plain("up"),), "top"),
        Tinted(None, "danger", (Styled("italic", (Plain("hot"),)),)),
        Citation("sop", 2),
        Placeholder("who"),
        ScriptText("subscript", "2"),
        InlineMath("x_i"),
    )

    assert write_runs(runs, _structured_writer()) == (
        ("text", "a ", ()),
        ("text", "b ", ("bold",)),
        ("text", "c", ("code", "link=https://example.com/x", "bold")),
        ("text", " d", ("link=https://example.com/x", "bold")),
        ("text", "up", ("anchor=top",)),
        ("text", "hot", ("italic", "tint=None/danger")),
        ("text", "[2]", ("citation=sop",)),
        ("placeholder", "who", ()),
        ("text", "2", ("subscript",)),
        ("math", "x_i", ()),
    )


def test_an_export_run_writer_builds_chips_breaks_marks_and_gauges_as_nodes_of_their_own() -> None:
    runs: ExportRich = (
        Chip("api", "blue"),
        Break(),
        Styled("bold", (Plain("lead"),)),
        StatusMark("done"),
        Gauge(3, 4),
    )

    assert write_export_runs(runs, _structured_writer()) == (
        ("status", "api", ("blue",)),
        ("hardBreak", "", ()),
        ("text", "lead", ("bold",)),
        ("status", "done", ()),
        ("gauge", "3/4", ()),
    )
