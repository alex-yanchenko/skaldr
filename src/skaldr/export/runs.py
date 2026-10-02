from dataclasses import dataclass
from typing import Protocol

from typing_extensions import assert_never

from skaldr.export.inline import one_line
from skaldr.models import BadgeColor, StatusState, SwimlaneStepState, ToneLiteral
from skaldr.richtext import Run, RunWriter, VisibleText, write_run


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


Mark = StatusMark | SwimlaneMark | IndicatorMark | CheckMark


@dataclass(frozen=True)
class Gauge:
    value: float
    maximum: float


ExportRun = Run | Chip | Break | Mark | Gauge
ExportRich = tuple[ExportRun, ...]


class ExportRunWriter(RunWriter, Protocol):
    def chip(self, run: Chip, /) -> str: ...

    def line_break(self) -> str: ...

    def mark(self, run: Mark, /) -> str: ...

    def gauge(self, run: Gauge, /) -> str: ...


def _write_export_run(run: ExportRun, writer: ExportRunWriter) -> str:
    match run:
        case Chip():
            return writer.chip(run)
        case Break():
            return writer.line_break()
        case StatusMark() | SwimlaneMark() | IndicatorMark() | CheckMark():
            return writer.mark(run)
        case Gauge():
            return writer.gauge(run)
        case _:
            return write_run(run, writer)


def write_export_runs(runs: ExportRich, writer: ExportRunWriter) -> str:
    return "".join(_write_export_run(run, writer) for run in runs)


def mark_name(mark: Mark) -> str:
    match mark:
        case StatusMark() | SwimlaneMark():
            return mark.state
        case IndicatorMark():
            return mark.tone
        case CheckMark():
            return "yes" if mark.checked else "no"
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


def export_visible_text(runs: ExportRich) -> str:
    return write_export_runs(runs, _ExportVisibleText())
