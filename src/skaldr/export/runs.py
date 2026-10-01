from dataclasses import dataclass
from typing import Literal, Protocol

from skaldr.models import BadgeColor
from skaldr.richtext import Run, RunWriter, VisibleText, write_run

MarkScheme = Literal["status", "timeline", "swimlane", "indicator", "check"]


@dataclass(frozen=True)
class Chip:
    label: str
    tone: BadgeColor


@dataclass(frozen=True)
class Break:
    pass


@dataclass(frozen=True)
class Mark:
    scheme: MarkScheme
    state: str


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
        case Mark():
            return writer.mark(run)
        case Gauge():
            return writer.gauge(run)
        case _:
            return write_run(run, writer)


def write_export_runs(runs: ExportRich, writer: ExportRunWriter) -> str:
    return "".join(_write_export_run(run, writer) for run in runs)


class _ExportVisibleText(VisibleText):
    def chip(self, run: Chip, /) -> str:
        return run.label

    def line_break(self) -> str:
        return " "

    def mark(self, run: Mark, /) -> str:
        return run.state

    def gauge(self, _run: Gauge, /) -> str:
        return ""


def export_visible_text(runs: ExportRich) -> str:
    return write_export_runs(runs, _ExportVisibleText())
