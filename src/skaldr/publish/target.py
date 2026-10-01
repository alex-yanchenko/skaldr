from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from skaldr.frozen_model import FrozenModel

Fields = dict[str, JsonValue]


class TargetOverride(FrozenModel):
    fields: Fields = Field(
        default_factory=dict[str, JsonValue],
        description="Field values for this one item, applied over the target's `where.fields`.",
    )


class PublishTargetBase(FrozenModel):
    model_config = ConfigDict(validate_by_alias=True, validate_by_name=False, serialize_by_alias=True)

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
        description="Per-item values keyed by a split section id.",
    )
    removed: Literal["archive", "delete"] = Field(
        default="archive",
        description="What happens to an item whose content left the document: `archive` is recoverable, "
        "`delete` is permanent. A Jira target accepts only `archive`.",
    )
    on_remote_edit: Literal["refuse", "overwrite"] = Field(
        default="refuse",
        description="When an item was edited in the service since the last publish: `refuse` stops and "
        "shows the change, `overwrite` replaces it.",
    )
