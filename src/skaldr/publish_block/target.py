from abc import abstractmethod
from typing import get_args

from pydantic import ConfigDict, Field, JsonValue

from skaldr.frozen_model import FrozenModel
from skaldr.services import SERVICES, Service

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

    @classmethod
    def service(cls) -> Service:
        to_field = cls.model_fields.get("to")
        names = () if to_field is None else get_args(to_field.annotation)
        if len(names) != 1 or names[0] not in SERVICES:
            raise TypeError(
                f"{cls.__name__} names no service: its `to` field must be a Literal of one of "
                f"{', '.join(SERVICES)}"
            )
        return names[0]

    @abstractmethod
    def where_fields(self) -> JsonFields: ...

    def fields_for(self, section_id: str | None) -> JsonFields:
        override = None if section_id is None else self.overrides.get(section_id)
        return {**self.where_fields(), **(override.fields if override is not None else {})}

    @abstractmethod
    def location_key(self) -> Location: ...

    @abstractmethod
    def location_label(self) -> str: ...

    def place_key(self) -> Location:
        return self.location_key()

    def place_label(self) -> str:
        return self.location_label()
