from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Final, Literal, TypeVar

from typing_extensions import Self

from skaldr.errors import (
    AuthError,
    ConnectorError,
    CreatedButUnfinishedError,
    ItemNotFoundError,
    WriteRejectedError,
)
from skaldr.publish.content import ItemContent
from skaldr.publish.transport import RawSections

UNKEYED_SECTION: Final = "content skaldr did not publish"

Answer = TypeVar("Answer")
PlacedRole = Literal["published", "added"]
Units = Callable[[str], Sequence[str]]


@dataclass(frozen=True)
class SectionLayout:
    keys: tuple[str, ...]
    units: tuple[str, ...]
    fallback: str

    @classmethod
    def of(cls, layout: Mapping[str, str], units_of: Units) -> Self:
        keys: list[str] = []
        units: list[str] = []
        for key, text in layout.items():
            expected = units_of(text)
            keys += [key] * len(expected)
            units += expected
        return cls(tuple(keys), tuple(units), next(iter(layout), UNKEYED_SECTION))

    def key_of_inserted(self, position: int) -> str:
        if not self.keys:
            return self.fallback
        opens_a_section = position < len(self.keys) and (
            position == 0 or self.keys[position] != self.keys[position - 1]
        )
        return self.keys[position] if opens_a_section else self.keys[position - 1]

    def placed(self, actual: Sequence[str]) -> list[tuple[str, PlacedRole]]:
        placed: list[tuple[str, PlacedRole]] = [(self.fallback, "added")] * len(actual)
        matcher = SequenceMatcher(None, self.units, actual, autojunk=False)
        for tag, start, end, actual_start, actual_end in matcher.get_opcodes():
            for offset, index in enumerate(range(actual_start, actual_end)):
                if tag == "equal":
                    placed[index] = (self.keys[start + offset], "published")
                elif tag == "replace":
                    position = start + offset * (end - start) // (actual_end - actual_start)
                    placed[index] = (self.keys[position], "added")
                else:
                    placed[index] = (self.key_of_inserted(start), "added")
        return placed


def comparable_sections(content: ItemContent, comparable_text: Callable[[str], str]) -> ItemContent:
    sections = {key: comparable_text(text) for key, text in content.sections.items()}
    return content.model_copy(update={"sections": {key: text for key, text in sections.items() if text}})


def refused_when_not_found(send: Callable[[], Answer]) -> Answer:
    try:
        return send()
    except (ItemNotFoundError, AuthError) as exc:
        raise WriteRejectedError(str(exc)) from exc


def finished_after_a_change(item: str, title: str, finish: Callable[[], Answer]) -> Answer:
    try:
        return finish()
    except (ConnectorError, AuthError) as exc:
        raise ConnectorError(
            f'skaldr wrote {item} for "{title}" but could not finish writing it: {exc}'
        ) from exc


def finished_after_a_create(item: str, item_id: str, title: str, finish: Callable[[], Answer]) -> Answer:
    try:
        return finish()
    except (ConnectorError, AuthError) as exc:
        raise CreatedButUnfinishedError(
            f'skaldr created {item} for "{title}" but could not finish writing it: {exc}; the next publish '
            "records it",
            item_id,
        ) from exc


def refuse_a_change_since_the_read(item: str, read: RawSections, now: RawSections) -> None:
    if list(now.items()) != list(read.items()):
        raise WriteRejectedError(
            f"{item} changed after skaldr read it, so nothing was written; publish again"
        )


@dataclass
class ReadLayouts:
    layouts: dict[str, Mapping[str, str]] = field(default_factory=dict[str, Mapping[str, str]])
    published: dict[str, Mapping[str, str]] = field(default_factory=dict[str, Mapping[str, str]])
    written: set[str] = field(default_factory=set[str])

    def note_the_read(self, key: str, keyed_like: ItemContent) -> None:
        if key not in self.written and keyed_like.sections:
            self.published[key] = keyed_like.sections

    def to_read(self, key: str, keyed_like: ItemContent) -> Mapping[str, str]:
        if key in self.written:
            return self.layouts[key]
        return keyed_like.sections or self.layouts.get(key, {})

    def note_written(self, key: str, layout: Mapping[str, str]) -> None:
        self.written.add(key)
        self.published[key] = layout

    def note_released(self, key: str) -> None:
        self.layouts[key] = {}
        self.published[key] = {}
        self.written.add(key)
