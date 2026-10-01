from dataclasses import dataclass
from typing import Literal, Protocol

from skaldr.models import BadgeColor
from skaldr.richtext import Run, RunWriter, VisibleText, write_run, write_sequence

MarkScheme = Literal["status", "timeline", "swimlane", "indicator", "delta", "check"]


@dataclass(frozen=True)
class Chip:
    label: str
    tone: BadgeColor


@dataclass(frozen=True)
class Mark:
    scheme: MarkScheme
    state: str


@dataclass(frozen=True)
class Gauge:
    value: float
    maximum: float


ExportRun = Run | Chip | Mark | Gauge
ExportRich = tuple[ExportRun, ...]


class ExportRunWriter(RunWriter, Protocol):
    def chip(self, run: Chip, /) -> str: ...

    def mark(self, run: Mark, /) -> str: ...

    def gauge(self, run: Gauge, /) -> str: ...


def _write_export_run(run: ExportRun, writer: ExportRunWriter) -> str:
    match run:
        case Chip():
            return writer.chip(run)
        case Mark():
            return writer.mark(run)
        case Gauge():
            return writer.gauge(run)
        case _:
            return write_run(run, writer)


def write_export_runs(runs: ExportRich, writer: ExportRunWriter) -> str:
    return write_sequence(runs, writer, _write_export_run)


class _ExportVisibleText(VisibleText):
    def chip(self, run: Chip, /) -> str:
        return run.label

    def mark(self, run: Mark, /) -> str:
        return run.state

    def gauge(self, _run: Gauge, /) -> str:
        return ""


def export_visible_text(runs: ExportRich) -> str:
    return write_export_runs(runs, _ExportVisibleText())
