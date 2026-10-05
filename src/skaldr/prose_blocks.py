import re
from dataclasses import dataclass, field
from typing import Final, Literal

LIST_ITEM_LINE: Final = re.compile(r"(?:(?P<bullet>[-*])|(?P<number>\d{1,9})[.)])[ \t]+(?P<text>\S.*)")
CONTINUATION_LINE: Final = re.compile(r"[ \t]+\S")
FEWEST_LIST_ITEMS: Final = 2

RunKind = Literal["text", "bullet", "number"]


@dataclass(frozen=True)
class ProseList:
    items: tuple[str, ...]
    start: int | None = None


ProseBlock = str | ProseList


@dataclass
class _Run:
    kind: RunKind
    lines: list[str] = field(default_factory=list[str])
    items: list[str] = field(default_factory=list[str])
    start: int | None = None

    def block(self) -> ProseBlock:
        if self.kind == "text":
            return "\n".join(self.lines).strip()
        return ProseList(tuple(self.items), self.start)


def paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def _continues_an_item(runs: list[_Run], line: str) -> bool:
    return bool(runs) and runs[-1].kind != "text" and CONTINUATION_LINE.match(line) is not None


def _marked_runs(paragraph: str) -> list[_Run]:
    runs: list[_Run] = []
    for line in paragraph.split("\n"):
        item = LIST_ITEM_LINE.fullmatch(line.strip())
        if _continues_an_item(runs, line):
            runs[-1].lines.append(line)
            runs[-1].items[-1] += " " + line.strip()
            continue
        kind: RunKind = "text" if item is None else "bullet" if item["bullet"] else "number"
        if not runs or runs[-1].kind != kind:
            start = int(item["number"]) if item is not None and item["number"] else None
            runs.append(_Run(kind, start=start))
        runs[-1].lines.append(line)
        if item is not None:
            runs[-1].items.append(item["text"].rstrip())
    return runs


def _with_short_lists_as_text(runs: list[_Run]) -> list[_Run]:
    merged: list[_Run] = []
    for run in runs:
        kind = run.kind if len(run.items) >= FEWEST_LIST_ITEMS or run.kind == "text" else "text"
        if kind == "text" and merged and merged[-1].kind == "text":
            merged[-1].lines.extend(run.lines)
        elif kind == "text":
            merged.append(_Run("text", list(run.lines)))
        else:
            merged.append(run)
    return merged


def prose_blocks(text: str) -> list[ProseBlock]:
    return [
        run.block()
        for paragraph in paragraphs(text)
        for run in _with_short_lists_as_text(_marked_runs(paragraph))
    ]


def rendered_strings(text: str) -> list[str]:
    strings: list[str] = []
    for block in prose_blocks(text):
        strings.extend([block] if isinstance(block, str) else block.items)
    return strings
