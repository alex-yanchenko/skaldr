from collections import defaultdict
from collections.abc import Iterable, Mapping
from functools import cached_property
from typing import Annotated, Any, Final, Literal, cast

from pydantic import Field, field_validator, model_validator

from skaldr.frozen_model import FrozenModel
from skaldr.models.base import BlockBase
from skaldr.models.primitives import (
    REFERENCE_KEY_PATTERN,
    BadgeColor,
    NonBlank,
    Number,
    SwimlaneStepState,
    require_url_scheme,
)


class SwimlaneStep(FrozenModel):
    lane: NonBlank = Field(description="Which lane this step sits in: one of the block's `lanes`.")
    col: NonBlank = Field(
        description="Which column (sprint) this step sits in: one of the block's `columns`. Two steps "
        "sharing a lane/col stack in that cell.",
    )
    n: NonBlank = Field(
        description="The number shown in the step's cell, a free string ('1', '3a', 'R1'); skaldr never "
        "derives or renumbers it, so it reads exactly as written.",
    )
    label: NonBlank = Field(description="Step label, shown beside the number.")
    group: str | None = Field(
        default=None,
        description="Which group (milestone) this step belongs to: one of the block's `groups` that covers "
        "its `col`. Required only when the column is split across more than one group; inferred otherwise.",
    )
    value: Number | None = Field(
        default=None,
        description="Optional numeric weight for this step (points, hours, cost, count: whatever the "
        "matrix measures). When any step in the block has a value, skaldr auto-sums them into per-column "
        "(footer row), per-lane (beside the lane label), and per-group (on the cap) totals, so the "
        "numbers never drift by hand. A step with no value counts as 0.",
    )
    url: str | None = Field(
        default=None,
        description="Optional link (http/https/mailto) for the step, e.g. its Jira/GitHub ticket. The "
        "step's number becomes a link out to it.",
    )
    state: SwimlaneStepState | None = Field(
        default=None,
        description="Progress state: the same progress axis as `status_list`/`timeline`, in roadmap "
        "terms (`todo` for not-started, plus `deferred`). `done` (green), "
        "`current` (in progress, the raised blue badge), `todo` (planned, not started; a cool "
        "filled slate badge), `blocked` (waiting / on-hold: amber + dashed), `deferred` (pushed out / "
        "post-MVP: a warm hollow badge that recedes). Unset, the HTML draws the step as `todo` and the "
        "Markdown exports show no state glyph. The value counts toward the totals in every state.",
    )

    @property
    def shown_state(self) -> SwimlaneStepState:
        return self.state or "todo"

    id: str | None = Field(
        default=None,
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Optional stable id (ASCII letters, digits, _, -) so other steps can point at this "
        "one via `depends_on`. Unique across the block's steps.",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Ids of steps this one depends on. The dependent renders a compact 'needs N' marker "
        "listing each referenced step's number. Each id must be a step's `id`; a step can't depend on "
        "itself.",
    )

    @model_validator(mode="after")
    def _url_scheme(self) -> "SwimlaneStep":
        require_url_scheme(self.url, "swimlane step url")
        return self


class SwimlaneLane(FrozenModel):
    name: NonBlank = Field(description="Lane label shown in the row gutter.")
    id: str | None = Field(
        default=None,
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Optional stable id (ASCII letters, digits, _, -) that a step references via `lane`; "
        "defaults to `name`. Set it to rename the displayed label without touching every step.",
    )

    @property
    def key(self) -> str:
        """The reference key steps use — the explicit id, or the name when no id is given."""
        return self.id if self.id is not None else self.name


class SwimlaneColumn(FrozenModel):
    name: NonBlank = Field(description="Column header label.")
    id: str | None = Field(
        default=None,
        min_length=1,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="Optional stable id (ASCII letters, digits, _, -) that a step references via `col` "
        "and a group via `columns`; defaults to `name`. Set it to rename the header without touching "
        "every step/group.",
    )
    sub: NonBlank | None = Field(
        default=None,
        description="Optional secondary caption under the header (e.g. a delivery target or date range).",
    )

    @property
    def key(self) -> str:
        """The reference key steps/groups use — the explicit id, or the name when no id is given."""
        return self.id if self.id is not None else self.name


class SwimlaneGroup(FrozenModel):
    name: NonBlank = Field(description="Group (milestone / delivery) name, shown on its cap.")
    color: BadgeColor = Field(
        description="Cap colour: a palette name (slate/blue/…) or its semantic tone twin (neutral/info/…). "
        "Author-chosen, never auto-assigned: a group's colour carries meaning."
    )
    columns: list[str] = Field(
        min_length=1,
        description="The columns this group spans, by their key (id, or name if no id): a CONTIGUOUS run "
        "of the block's `columns` (a group cannot skip a column). Order need not match; it is derived "
        "from the block `columns`.",
    )


def _first_and_last_index(keys: Iterable[str | None]) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    for index, key in enumerate(keys):
        if key is not None:
            spans[key] = (spans[key][0], index) if key in spans else (index, index)
    return spans


MAX_SWIMLANE_LANES: Final = 8


def _wrap_bare_names(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    return [{"name": item} if isinstance(item, str) else item for item in cast("list[object]", value)]


class Swimlane(BlockBase):
    type: Literal["swimlane"]
    lanes: list[SwimlaneLane] = Field(
        min_length=1,
        max_length=MAX_SWIMLANE_LANES,
        description="Lanes, in row order (top to bottom). A bare string is shorthand for `{name: …}`; "
        f"use `{{id, name}}` to give a stable reference key. Capped at {MAX_SWIMLANE_LANES}: more rows "
        "than that stop reading as a matrix; split into two swimlanes instead.",
    )
    columns: list[SwimlaneColumn] = Field(
        min_length=1,
        description="Columns, left to right: the sprint / phase axis. A bare string is shorthand for "
        "`{name: …}`; use `{id, name, sub}` for a stable key and/or a secondary header caption.",
    )
    groups: list[SwimlaneGroup] = Field(
        default_factory=list[SwimlaneGroup],
        description="Optional milestone overlay: coloured caps beyond the table, each spanning a contiguous "
        "run of columns. Omit entirely for a plain swimlane.",
    )
    steps: list[SwimlaneStep] = Field(
        min_length=1, description="Steps placed on the lane/column grid; the sequence reads as a staircase."
    )

    @field_validator(
        "lanes",
        mode="before",
        json_schema_input_type=Annotated[
            list[NonBlank | SwimlaneLane], Field(min_length=1, max_length=MAX_SWIMLANE_LANES)
        ],
    )
    @classmethod
    def _wrap_bare_lane_names(cls, value: Any) -> Any:
        return _wrap_bare_names(value)

    @field_validator(
        "columns",
        mode="before",
        json_schema_input_type=Annotated[list[NonBlank | SwimlaneColumn], Field(min_length=1)],
    )
    @classmethod
    def _wrap_bare_column_names(cls, value: Any) -> Any:
        return _wrap_bare_names(value)

    def _groups_covering(self, col: str) -> list[SwimlaneGroup]:
        return [group for group in self.groups if col in group.columns]

    @cached_property
    def _number_by_id(self) -> dict[str, str]:
        return {step.id: step.n for step in self.steps if step.id is not None}

    def dependency_numbers(self, step: SwimlaneStep) -> list[str]:
        return list(dict.fromkeys(self._number_by_id[dependency] for dependency in step.depends_on))

    @cached_property
    def _placed_steps(self) -> dict[tuple[str, str, str | None], tuple[SwimlaneStep, ...]]:
        placed: defaultdict[tuple[str, str, str | None], list[SwimlaneStep]] = defaultdict(list)
        for step in self.steps:
            placed[(step.lane, step.col, self.step_group(step))].append(step)
        return {placement: tuple(steps) for placement, steps in placed.items()}

    def steps_at(self, lane: str, col: str, group: str | None) -> tuple[SwimlaneStep, ...]:
        return self._placed_steps.get((lane, col, group), ())

    @cached_property
    def group_spans(self) -> Mapping[str, tuple[int, int]]:
        return _first_and_last_index(group for _, group in self.subcolumns())

    @cached_property
    def column_spans(self) -> Mapping[str, tuple[int, int]]:
        return _first_and_last_index(column for column, _ in self.subcolumns())

    def step_group(self, step: SwimlaneStep) -> str | None:
        """The group a step resolves to: its explicit `group`, else the sole group covering its column,
        else None (an ungrouped column)."""
        if step.group is not None:
            return step.group
        covering = self._groups_covering(step.col)
        return covering[0].name if len(covering) == 1 else None

    def subcolumns(self) -> tuple[tuple[str, str | None], ...]:
        return self._segments

    @cached_property
    def _segments(self) -> tuple[tuple[str, str | None], ...]:
        """The ordered atomic (column, group-name) segments the grid is built from. A column with no
        group → one `(col, None)` segment; a column split across N groups → N segments in canonical
        order (by column span, then declaration order). Raises if a group's segments cannot be laid out
        contiguously (it interleaves with another group instead of nesting)."""
        if not self.groups:
            return tuple((col.key, None) for col in self.columns)
        col_index = {col.key: index for index, col in enumerate(self.columns)}
        group_index = {group.name: index for index, group in enumerate(self.groups)}

        def span(group: "SwimlaneGroup") -> tuple[int, int]:
            indices = [col_index[col] for col in group.columns]
            return min(indices), max(indices)

        segments: list[tuple[str, str | None]] = []
        for col in self.columns:
            covering = sorted(
                self._groups_covering(col.key),
                key=lambda group: (*span(group), group_index[group.name]),
            )
            if covering:
                segments.extend((col.key, group.name) for group in covering)
            else:
                segments.append((col.key, None))
        for group in self.groups:
            positions = [index for index, (_, name) in enumerate(segments) if name == group.name]
            if positions and positions != list(range(positions[0], positions[-1] + 1)):
                raise ValueError(
                    f"swimlane group '{group.name}' cannot be laid out contiguously: it shares a column "
                    "with another group while spanning past it; groups must nest, not interleave"
                )
        return tuple(segments)

    @model_validator(mode="after")
    def _shape(self) -> "Swimlane":
        lane_keys = [lane.key for lane in self.lanes]
        col_keys = [col.key for col in self.columns]
        if len(set(lane_keys)) != len(lane_keys):
            raise ValueError("swimlane lanes must be unique")
        if len(set(col_keys)) != len(col_keys):
            raise ValueError("swimlane columns must be unique")
        lane_set = set(lane_keys)
        col_set = set(col_keys)
        col_index = {col: index for index, col in enumerate(col_keys)}

        group_names = [group.name for group in self.groups]
        if len(set(group_names)) != len(group_names):
            raise ValueError("swimlane group names must be unique")
        for group in self.groups:
            undeclared = [col for col in group.columns if col not in col_set]
            if undeclared:
                raise ValueError(
                    f"swimlane group '{group.name}' references undeclared column(s): {', '.join(undeclared)}"
                )
            indices = sorted(col_index[col] for col in group.columns)
            if indices != list(range(indices[0], indices[-1] + 1)):
                raise ValueError(f"swimlane group '{group.name}' columns must be contiguous in column order")

        group_name_set = set(group_names)
        for step in self.steps:
            if step.lane not in lane_set:
                raise ValueError(f"swimlane step lane '{step.lane}' is not one of the declared lanes")
            if step.col not in col_set:
                raise ValueError(f"swimlane step col '{step.col}' is not one of the declared columns")
            covering = {group.name for group in self._groups_covering(step.col)}
            if step.group is not None:
                if step.group not in group_name_set:
                    raise ValueError(f"swimlane step group '{step.group}' is not a declared group")
                if step.group not in covering:
                    raise ValueError(f"swimlane step group '{step.group}' does not cover column '{step.col}'")
            elif len(covering) > 1:
                raise ValueError(
                    f"swimlane step in column '{step.col}' must name a group: that column is split across "
                    f"{len(covering)} groups"
                )

        used_lanes = {step.lane for step in self.steps}
        for lane in self.lanes:
            if lane.key not in used_lanes:
                raise ValueError(f"swimlane lane '{lane.key}' has no steps")
        used_cols = {step.col for step in self.steps}
        for col in self.columns:
            if col.key not in used_cols:
                raise ValueError(f"swimlane column '{col.key}' has no steps")
        used_groups = {resolved for step in self.steps if (resolved := self.step_group(step)) is not None}
        for group in self.groups:
            if group.name not in used_groups:
                raise ValueError(f"swimlane group '{group.name}' has no steps")

        step_ids = [step.id for step in self.steps if step.id is not None]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("swimlane step ids must be unique")
        id_set = set(step_ids)
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in id_set:
                    raise ValueError(f"swimlane step depends_on references unknown step id '{dep}'")
                if dep == step.id:
                    raise ValueError(f"swimlane step '{dep}' cannot depend on itself")

        self.subcolumns()  # trigger the contiguity / ordering check
        return self
