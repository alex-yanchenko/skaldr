import os
from collections import Counter
from collections.abc import Iterator, Sequence
from functools import cached_property
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import AfterValidator, ConfigDict, Field, JsonValue, field_validator, model_validator

from skaldr.frozen_model import FrozenModel
from skaldr.models.comparison_matrix import Matrix
from skaldr.models.containers import AnyBlock, PageBlock, Section
from skaldr.models.meta import Badge, Meta
from skaldr.models.primitives import NonBlank
from skaldr.models.request import Request, RequestFlow
from skaldr.models.simple_blocks import Card, Cards, Heading, References
from skaldr.models.table import Table
from skaldr.models.walk import iter_located_badge_keys, walk_located_blocks
from skaldr.publish_block import Publish, section_choice_errors


def _relative_part_path(path: str) -> str:
    if Path(path).is_absolute():
        raise ValueError(f"a part path is relative to the index file, not absolute: {path}")
    if Path(os.path.normpath(path)).parts[:1] == ("..",):
        raise ValueError(f"a part path stays inside the index file's folder, not above it: {path}")
    return path


PartPath = Annotated[NonBlank, AfterValidator(_relative_part_path)]


class Index(FrozenModel):
    layout: Literal["one_page"] = Field(
        default="one_page",
        description="How the parts combine: `one_page` builds one page holding every part in order, each "
        "under its own title.",
    )
    parts: list[PartPath] = Field(
        min_length=1,
        description="The skaldr documents this index combines, in order, each a path relative to the index "
        "file. A part's `meta.title` becomes its part title; its blocks follow unchanged; its badges merge "
        "into the page. A part cannot be an index itself.",
    )
    collapsed: bool = Field(
        default=False,
        description="Whether every part starts collapsed (a collapsible in HTML, a toggle heading in the "
        "exports). Default false: every part is open.",
    )

    @field_validator("parts")
    @classmethod
    def _each_part_listed_once(cls, parts: list[str]) -> list[str]:
        repeated = sorted({part for part, count in Counter(parts).items() if count > 1})
        if repeated:
            raise ValueError(f"a part is listed more than once: {', '.join(repeated)}; list each part once")
        return parts


_BLOCKS_OR_AN_INDEX_IN_SCHEMA: Final[dict[str, JsonValue]] = {
    "anyOf": [{"required": ["blocks"]}, {"required": ["index"]}]
}


class Report(FrozenModel):
    model_config = ConfigDict(json_schema_extra=_BLOCKS_OR_AN_INDEX_IN_SCHEMA)

    version: Literal[1] = Field(description="Content-file schema version.")
    meta: Meta
    badges: dict[str, Badge] = Field(
        default_factory=dict, description="Author-declared tag/status vocabulary."
    )
    index: Index | None = Field(
        default=None,
        description="Makes this document an index: one page built from other skaldr documents. `blocks` "
        "becomes optional and, when present, opens the page before the first part.",
    )
    blocks: list[PageBlock] = Field(default_factory=list[PageBlock], min_length=1)
    publish: Publish | None = Field(
        default=None,
        description="Where the document publishes (Notion pages, Jira issues, Slack canvases). Omitted from "
        "the source embedded in a rendered page. Not yet accepted on an index document.",
    )

    @model_validator(mode="after")
    def _refuse_an_index_that_was_not_loaded(self) -> "Report":
        if self.index is not None:
            raise ValueError(
                "`index` is read when its file is loaded, which brings in every part; load the index file "
                "rather than its parsed data"
            )
        return self

    @model_validator(mode="after")
    def _refuse_a_page_without_blocks(self) -> "Report":
        if not self.blocks:
            raise ValueError("`blocks` needs at least one block; only an index document may leave it out")
        return self

    @model_validator(mode="after")
    def _validate_publish_sections(self) -> "Report":
        if self.publish is None:
            return self
        section_ids = [block.id for block in self.blocks if isinstance(block, Section) and block.id]
        errors = section_choice_errors(self.publish, section_ids)
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @model_validator(mode="after")
    def _validate_badge_references(self) -> "Report":
        undeclared = [
            (path, key) for path, key in iter_located_badge_keys(self.blocks) if key not in self.badges
        ]
        if undeclared:
            keys = sorted({key for _, key in undeclared})
            where = ", ".join(f"{path} ({key!r})" for path, key in undeclared)
            raise ValueError(
                f"badge key(s) not declared in `badges`: {keys}, at {where}; add them to the badges map"
            )
        return self

    @cached_property
    def located_blocks(self) -> list[tuple[str, AnyBlock]]:
        return list(walk_located_blocks(self.blocks))

    def _located_cards(self) -> Iterator[tuple[str, Card]]:
        for path, block in self.located_blocks:
            if isinstance(block, Cards):
                for index, card in enumerate(block.items):
                    yield f"{path}.items.{index}", card

    @model_validator(mode="after")
    def _validate_matrix_references(self) -> "Report":
        placed = [
            (f"{path}.id", block.id)
            for path, block in self.located_blocks
            if isinstance(block, Matrix) and block.id is not None
        ]
        _refuse_repeats(placed, "matrix id(s)", "matrix ids must be unique")
        matrix_ids = {matrix_id for _, matrix_id in placed}
        for path, card in self._located_cards():
            if card.of_matrix is not None and card.of_matrix not in matrix_ids:
                raise ValueError(
                    f"card of_matrix names '{card.of_matrix}', which is not the id of any matrix, at "
                    f"{path}.of_matrix"
                )
        return self

    @model_validator(mode="after")
    def _validate_table_references(self) -> "Report":
        tables = [
            (f"{path}.id", block.id, block)
            for path, block in self.located_blocks
            if isinstance(block, Table) and block.id is not None
        ]
        _refuse_repeats(
            [(path, table_id) for path, table_id, _ in tables], "table id(s)", "table ids must be unique"
        )
        rollups = {table_id: table.rollup is not None for _, table_id, table in tables}
        for path, card in self._located_cards():
            for index, table_id in enumerate(card.of_tables or []):
                where = f"{path}.of_tables.{index}"
                if table_id not in rollups:
                    raise ValueError(
                        f"card of_tables names '{table_id}', which is not the id of any table, at {where}"
                    )
                if not rollups[table_id]:
                    raise ValueError(
                        f"card of_tables names '{table_id}', which is a table with no `rollup`, at {where}; "
                        "of_tables counts a badge with each table's rollup column, so the table must "
                        "declare one"
                    )
        return self

    @model_validator(mode="after")
    def _validate_request_storage_keys_unique(self) -> "Report":
        _refuse_repeats(
            [
                (path, block.id or block.label)
                for path, block in self.located_blocks
                if isinstance(block, Request | RequestFlow)
            ],
            "request block label(s)",
            "request labels must be unique, because a label keys what a reader's fields are remembered "
            "under while their tab is open: give one of them an `id`",
        )
        return self

    @model_validator(mode="after")
    def _validate_reference_keys_unique(self) -> "Report":
        _refuse_repeats(
            [
                (f"{path}.items.{index}.key", item.key)
                for path, block in self.located_blocks
                if isinstance(block, References)
                for index, item in enumerate(block.items)
            ],
            "reference key(s)",
            "reference keys must be unique",
        )
        return self

    @model_validator(mode="after")
    def _validate_section_links_name_sections(self) -> "Report":
        section_ids = {
            block.id for _, block in self.located_blocks if isinstance(block, Section) and block.id
        }
        for path, block in self.located_blocks:
            if not isinstance(block, Section) or block.fields is None:
                continue
            for link_type, targets in block.fields.links.items():
                for index, target in enumerate(targets):
                    if target not in section_ids:
                        raise ValueError(
                            f"section link '{link_type}' names '{target}', which is not the id of any "
                            f"section, at {path}.fields.links.{link_type}.{index}"
                        )
        return self

    @model_validator(mode="after")
    def _validate_anchor_ids_unique(self) -> "Report":
        _refuse_repeats(
            [
                (f"{path}.id", block.id)
                for path, block in self.located_blocks
                if isinstance(block, Heading | Section) and block.id is not None
            ],
            "heading/section id(s)",
            "heading and section ids must be unique",
        )
        return self


def _refuse_repeats(placed: Sequence[tuple[str, str]], what: str, reason: str) -> None:
    counts = Counter(value for _, value in placed)
    repeated = sorted(value for value, count in counts.items() if count > 1)
    if repeated:
        where = ", ".join(path for path, value in placed if counts[value] > 1)
        raise ValueError(f"{what} used more than once: {repeated}, at {where}; {reason}")
