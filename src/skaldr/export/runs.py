from dataclasses import dataclass
from typing import Protocol

from skaldr.export.inline import one_line
from skaldr.models import BadgeColor, StatusState
from skaldr.richtext import Run, RunWriter, VisibleText, write_run


@dataclass(frozen=True)
class Chip:
    label: str
    tone: BadgeColor

    @classmethod
    def on_one_line(cls, label: str, tone: BadgeColor) -> "Chip":
        return cls(one_line(label), tone)


@dataclass(frozen=True)
class StatusMark:
    state: StatusState


Mark = StatusMark


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
        case StatusMark():
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

    def mark(self, run: Mark, /) -> str:
        return run.state

    def gauge(self, _run: Gauge, /) -> str:
        return ""


def export_visible_text(runs: ExportRich) -> str:
    return write_export_runs(runs, _ExportVisibleText())
