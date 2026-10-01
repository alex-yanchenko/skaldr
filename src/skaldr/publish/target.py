from abc import abstractmethod
from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from skaldr.frozen_model import FrozenModel

JsonFields = dict[str, JsonValue]
Location = tuple[str, ...]


class TargetOverride(FrozenModel):
    fields: JsonFields = Field(
        default_factory=JsonFields,
        description="Field values for this one item, applied over the target's `where.fields`.",
    )


class TargetBase(FrozenModel):
    model_config = ConfigDict(validate_by_name=False, serialize_by_alias=True)

    from_sections: list[str] | None = Field(
        default=None,
        min_length=1,
        validation_alias="from",
        serialization_alias="from",
        description="Top-level section ids this target is built from, kept in document order. Left out: "
        "the whole document.",
    )
    split: list[str] = Field(
        default_factory=list[str],
        description="Top-level section ids that each become their own child page or child issue; "
        "everything else stays on the document's own page or issue. Left out: one item for the document.",
    )
    overrides: dict[str, TargetOverride] = Field(
        default_factory=dict[str, TargetOverride],
        description="Per-item field values keyed by a split section id, applied over `where.fields`.",
    )
    on_remote_edit: Literal["refuse", "overwrite"] = Field(
        default="refuse",
        description="When an item was edited in the service since the last publish: `refuse` stops and "
        "shows the change, `overwrite` replaces it.",
    )

    @abstractmethod
    def location_key(self) -> Location: ...

    @abstractmethod
    def location_label(self) -> str: ...
