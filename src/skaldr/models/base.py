from pydantic import Field

from skaldr.frozen_model import FrozenModel
from skaldr.models.primitives import SixthsCount


class BlockBase(FrozenModel):
    """Base for every top-level/section block. Carries the one width primitive: `span`, how many of
    the 6 content columns the block occupies. It is width only; blocks still stack vertically (one per
    row). To place several blocks in a single row, use a `grid` (whose cells carry their own span)."""

    span: SixthsCount | None = Field(
        default=None,
        description="Block width in content columns (1 to 6); omit for full width. Same column-count "
        "vocabulary as a grid cell's span, relative to the block's container (the page, or the "
        "enclosing grid cell when nested). Width only: blocks still stack vertically; use a `grid` to "
        "put several in one row.",
    )
