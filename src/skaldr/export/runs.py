from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from typing_extensions import assert_never

from skaldr.export.inline import one_line
from skaldr.models import BadgeColor, StatusState, SwimlaneStepState, ToneLiteral
from skaldr.richtext import (
    AnchorLink,
    DateMention,
    DocumentLink,
    IssueLink,
    Link,
    PersonMention,
    Rich,
    Run,
    RunWriter,
    Styled,
    Tinted,
    VisibleText,
    Written,
    write_run,
    write_runs,
)


@dataclass(frozen=True)
class Chip:
    label: str
    tone: BadgeColor

    @classmethod
    def on_one_line(cls, label: str, tone: BadgeColor) -> "Chip":
        return cls(one_line(label), tone)


@dataclass(frozen=True)
class Break:
    pass


@dataclass(frozen=True)
class StatusMark:
    state: StatusState


@dataclass(frozen=True)
class SwimlaneMark:
    state: SwimlaneStepState


@dataclass(frozen=True)
class IndicatorMark:
    tone: ToneLiteral


@dataclass(frozen=True)
class CheckMark:
    checked: bool


@dataclass(frozen=True)
class DecisionMark:
    decided: bool


Mark = StatusMark | SwimlaneMark | IndicatorMark | CheckMark | DecisionMark


@dataclass(frozen=True)
class Gauge:
    value: float
    maximum: float


@dataclass(frozen=True)
class SectionLink:
    label: Rich
    anchor: str


@dataclass(frozen=True)
class TonedLabel:
    tone: ToneLiteral
    runs: Rich


ChiplessExportRun = Run | Break | Mark | Gauge | SectionLink | TonedLabel
ExportRun = ChiplessExportRun | Chip
ExportRich = tuple[ExportRun, ...]


def every_run(runs: Iterable[ExportRun]) -> Iterator[ExportRun]:
    for run in runs:
        yield run
        match run:
            case (
                Link()
                | AnchorLink()
                | DateMention()
                | PersonMention()
                | IssueLink()
                | DocumentLink()
                | SectionLink()
            ):
                yield from every_run(run.label)
            case Styled() | Tinted() | TonedLabel():
                yield from every_run(run.runs)
            case _:
                pass


def holds_a_chip(runs: ExportRich) -> bool:
    return any(isinstance(run, Chip) for run in runs)


class ChiplessExportRunWriter(RunWriter[Written], Protocol[Written]):
    def line_break(self) -> Written: ...

    def mark(self, run: Mark, /) -> Written: ...

    def gauge(self, run: Gauge, /) -> Written: ...

    def section_link(self, label: Written, anchor: str, /) -> Written: ...

    def toned_label(self, tone: ToneLiteral, inner: Written, /) -> Written: ...


class ExportRunWriter(ChiplessExportRunWriter[Written], Protocol[Written]):
    def chip(self, run: Chip, /) -> Written: ...


def write_chipless_export_run(run: ChiplessExportRun, writer: ChiplessExportRunWriter[Written]) -> Written:
    match run:
        case Break():
            return writer.line_break()
        case StatusMark() | SwimlaneMark() | IndicatorMark() | CheckMark() | DecisionMark():
            return writer.mark(run)
        case Gauge():
            return writer.gauge(run)
        case SectionLink():
            return writer.section_link(write_runs(run.label, writer), run.anchor)
        case TonedLabel():
            return writer.toned_label(run.tone, write_runs(run.runs, writer))
        case _:
            return write_run(run, writer)


def write_export_run(run: ExportRun, writer: ExportRunWriter[Written]) -> Written:
    match run:
        case Chip():
            return writer.chip(run)
        case _:
            return write_chipless_export_run(run, writer)


def write_export_runs(runs: ExportRich, writer: ExportRunWriter[Written]) -> Written:
    return writer.concat([write_export_run(run, writer) for run in runs])


def mark_name(mark: Mark) -> str:
    match mark:
        case StatusMark() | SwimlaneMark():
            return mark.state
        case IndicatorMark():
            return mark.tone
        case CheckMark():
            return "yes" if mark.checked else "no"
        case DecisionMark():
            return "decided" if mark.decided else "open"
        case _:
            assert_never(mark)


class _ExportVisibleText(VisibleText):
    def chip(self, run: Chip, /) -> str:
        return run.label

    def line_break(self) -> str:
        return " "

    def mark(self, run: Mark, /) -> str:
        return mark_name(run)

    def gauge(self, _run: Gauge, /) -> str:
        return ""

    def section_link(self, label: str, _anchor: str, /) -> str:
        return label

    def toned_label(self, _tone: ToneLiteral, inner: str, /) -> str:
        return inner


def export_visible_text(runs: ExportRich) -> str:
    return write_export_runs(runs, _ExportVisibleText())
