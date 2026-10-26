from collections.abc import Mapping, Sequence
from typing import Annotated, Final, Literal, cast

from pydantic import Field, ValidationInfo, model_validator
from pydantic.json_schema import SkipJsonSchema

from skaldr.frozen_model import FrozenModel
from skaldr.models.base import BlockBase
from skaldr.models.comparison_matrix import Comparison, Matrix
from skaldr.models.primitives import (
    ANCHOR_ID_PATTERN,
    MAX_STRIP_LABELS,
    NUMBER_GUARD,
    NonBlank,
    NonBlankRichText,
    SixthsCount,
    Tone,
    check_distinct_strip_labels,
)
from skaldr.models.request import Request, RequestFlow, RequestStep
from skaldr.models.section_fields import SectionFields
from skaldr.models.simple_blocks import (
    BadgeRow,
    Callout,
    Cards,
    Chart,
    Code,
    DefList,
    Divider,
    FactStrip,
    Fan,
    Flow,
    Heading,
    Image,
    KeyValue,
    Link,
    ListBlock,
    Math,
    Media,
    Meter,
    Note,
    Quote,
    Range,
    References,
    StatusList,
    Text,
    Timeline,
)
from skaldr.models.swimlane import Swimlane
from skaldr.models.table import Table


class _ToggleBase(BlockBase):
    type: Literal["toggle"]
    title: NonBlank = Field(description="Summary label shown on the collapsible.")
    collapsed: bool = Field(
        default=True,
        description="Whether the toggle starts collapsed, as a section does. Set false to open it.",
    )


class InnerToggle(_ToggleBase):
    blocks: list["InnerBlock"] = Field(
        min_length=1,
        description="Blocks inside a toggle in a grid cell, a walkthrough step's detail or a tab: any block "
        "except a section, panel, grid, walkthrough, request or request_flow. It may hold another toggle "
        "or a tabs block.",
    )


class Toggle(_ToggleBase):
    blocks: list["SectionBlock"] = Field(
        min_length=1,
        description="Blocks inside a toggle at the top level, in a section, in a panel or in another such "
        "toggle: any block a section holds, including a request or request_flow.",
    )


class Tab(FrozenModel):
    label: NonBlank = Field(description="The tab's label in the strip, and its heading on paper.")
    tone: Tone | None = Field(
        default=None,
        description="Optional tone: a coloured dot before the label, the way a request case shows its "
        "outcome. Omit it for a plain label.",
    )
    blocks: list["InnerBlock"] = Field(
        min_length=1,
        description="Blocks shown while the tab is chosen: any block a toggle in a grid cell holds, "
        "including a toggle or another tabs block, and never a request or request_flow.",
    )


class Tabs(BlockBase):
    type: Literal["tabs"]
    tabs: list[Tab] = Field(
        min_length=2,
        max_length=MAX_STRIP_LABELS,
        description=f"The tabs, in strip order; the first starts chosen. Two to {MAX_STRIP_LABELS}, with "
        "distinct labels. Every tab prints, each under its label.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "Tabs":
        check_distinct_strip_labels((tab.label for tab in self.tabs), "tabs repeat a label")
        return self


_Simple = (
    Heading
    | Text
    | ListBlock
    | FactStrip
    | KeyValue
    | DefList
    | Cards
    | BadgeRow
    | Callout
    | StatusList
    | Meter
    | Range
    | Table
    | Code
    | Math
    | Quote
    | Note
    | Divider
    | Image
    | Media
    | Link
    | Timeline
    | Flow
    | Fan
    | Chart
    | Comparison
    | Matrix
    | Swimlane
    | References
)
_Leaf = _Simple | InnerToggle | Tabs
InnerBlock = Annotated[_Leaf, Field(discriminator="type")]
InnerToggle.model_rebuild()
Tab.model_rebuild()
FullWidthBlock = Annotated[_Simple | Toggle | Tabs | Request | RequestFlow, Field(discriminator="type")]
RequestLike = Request | RequestStep


class Section(BlockBase):
    type: Literal["section"]
    title: NonBlank = Field(description="Summary label shown on the collapsible.")
    id: str | None = Field(
        default=None,
        pattern=rf"^{ANCHOR_ID_PATTERN}$",
        description="Optional stable anchor id (lowercase, hyphen-separated). Overrides the title-derived "
        "slug so `[…](#id)` links survive a title rename. Must be unique across the page.",
    )
    fields: SectionFields | None = Field(
        default=None,
        description="Issue fields and page properties shown as a fact strip under the title: status, "
        "priority, assignee, due, labels, estimate, `links` to other sections by id, and any extra key "
        "holding a string, a number or a list of them.",
    )
    collapsed: bool = Field(
        default=True,
        description="Whether the section starts collapsed. Default true suits an appendix / detail; set "
        "false for a read-through living doc so the section opens expanded.",
    )
    updated: str | None = Field(
        default=None,
        description="When this section was last revised; shown as a muted stamp in its header. A "
        "free-form label like the report date (author it; never auto-now).",
    )
    blocks: list["SectionBlock"] = Field(
        min_length=1,
        description="Blocks in the section: any block except another section, grid, or walkthrough.",
    )


class Panel(BlockBase):
    type: Literal["panel"]
    title: NonBlank = Field(description="Panel title, shown in the header band.")
    blocks: list[FullWidthBlock] = Field(
        min_length=1,
        description="Blocks inside the panel: any block except another panel, section, grid, or "
        "walkthrough. Unlike a `section`, a panel is always open: "
        "a titled framed card, one per 'slide' in a deck-style doc.",
    )


SectionBlock = Annotated[_Simple | Toggle | Tabs | Request | RequestFlow | Panel, Field(discriminator="type")]
Toggle.model_rebuild()
Section.model_rebuild()
Panel.model_rebuild()


class InnerGridCell(FrozenModel):
    span: SixthsCount = Field(description="Columns this cell spans, of 6.")
    blocks: list[InnerBlock] = Field(min_length=1, description="Leaf blocks stacked in the cell.")
    tone: Tone | None = Field(
        default=None,
        description="Optional tone: turns the cell into an emphasis panel (accent top-border + tint). "
        "Use `neutral` for a muted aside, `accent`/`success` for a primary panel.",
    )


class InnerGrid(BlockBase):
    type: Literal["grid"]
    cells: list[InnerGridCell] = Field(min_length=1, description="Cells across the 6-column row.")

    @model_validator(mode="after")
    def _spans_fit(self) -> "InnerGrid":
        _check_span_sum(self.cells)
        return self


CellBlock = Annotated[_Leaf | InnerGrid, Field(discriminator="type")]


class GridCell(FrozenModel):
    span: SixthsCount = Field(description="Columns this cell spans, of 6.")
    blocks: list[CellBlock] = Field(
        min_length=1, description="Blocks stacked in the cell; may include nested grids (depth 2 max)."
    )
    tone: Tone | None = Field(
        default=None,
        description="Optional tone: turns the cell into an emphasis panel (accent top-border + tint). "
        "Use `neutral` for a muted aside, `accent`/`success` for a primary panel.",
    )


class Grid(BlockBase):
    type: Literal["grid"]
    cells: list[GridCell] = Field(min_length=1, description="Cells across a 6-column row.")

    @model_validator(mode="after")
    def _spans_fit(self) -> "Grid":
        _check_span_sum(self.cells)
        return self


def _check_span_sum(cells: Sequence[GridCell | InnerGridCell]) -> None:
    total = sum(cell.span for cell in cells)
    if total > 6:
        raise ValueError(f"cell spans sum to {total}; must total at most 6")


class WalkthroughStep(FrozenModel):
    label: NonBlank = Field(
        description="Step title: a few words to a short sentence; it wraps across lines, so it can be long.",
    )
    sub: NonBlankRichText | None = Field(
        default=None, description="Optional one-line sub-label under the title (rich text)."
    )
    tone: Tone | None = Field(
        default=None,
        description="Optional tone for the step's left rail. Every step always HAS the rail (it is the "
        "list's structure); tone only changes its colour, so use it to mark a key step, not every "
        "step. The numeral stays a uniform muted grey regardless, so tones can't leave steps mismatched.",
    )
    detail: list[CellBlock] = Field(
        min_length=1,
        description="The step's detail (paragraphs, lists, code, callouts, tables, or a `grid` for a "
        "two-column step like Action | Script), rendered in the column beside the numbered title.",
    )


class Walkthrough(BlockBase):
    type: Literal["walkthrough"]
    steps: list[WalkthroughStep] = Field(
        min_length=1,
        description="Ordered steps; each is a big numbered title beside its detail column.",
    )
    step_span: Annotated[int, Field(ge=1, le=5), NUMBER_GUARD] = Field(
        default=2,
        description="Width of the title column, of 6; the detail column takes the rest (default 2).",
    )


_TopLevel = _Simple | Toggle | Tabs | Request | RequestFlow | Section | Grid | Walkthrough | Panel
Block = Annotated[_TopLevel, Field(discriminator="type")]

BUILT_BY_AN_INDEX: Final = "built_by_an_index"


def _is_built_by_an_index(info: ValidationInfo) -> bool:
    context: object = info.context
    return (
        isinstance(context, Mapping) and cast("Mapping[str, object]", context).get(BUILT_BY_AN_INDEX) is True
    )


class Part(FrozenModel):
    type: Literal["part"]
    title: NonBlank
    doc_id: str | None = Field(default=None, exclude=True)
    collapsed: bool = False
    blocks: list[Block] = Field(min_length=1)

    @model_validator(mode="after")
    def _only_an_index_builds_a_part(self, info: ValidationInfo) -> "Part":
        if not _is_built_by_an_index(info):
            raise ValueError(
                "a `part` block is built by an `index`, not written by hand; list the file under "
                "`index.parts`, or use a `section` or a `heading`"
            )
        return self


PageBlock = Annotated[_TopLevel | SkipJsonSchema[Part], Field(discriminator="type")]
# Every node the tree-walkers (badge/heading/table recursion) may descend into.
AuthoredBlock = _Leaf | Toggle | Request | RequestFlow | Section | Panel | Grid | InnerGrid | Walkthrough
AnyBlock = AuthoredBlock | Part
