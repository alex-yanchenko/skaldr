import math
from collections.abc import Mapping
from datetime import date
from typing import Annotated, Any, Final, cast

from pydantic import BeforeValidator, ConfigDict, Field, model_validator

from skaldr.frozen_model import FrozenModel
from skaldr.models.primitives import ANCHOR_ID_PATTERN, NonBlank, NonNegativeNumber, Number


def _iso_date_from_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"due must be an ISO date such as 2026-10-15, not {value!r}") from error


IsoDate = Annotated[date, BeforeValidator(_iso_date_from_text)]
FieldScalar = NonBlank | Number
FieldList = Annotated[list[FieldScalar], Field(min_length=1)]
SectionLinks = dict[
    NonBlank, Annotated[list[Annotated[str, Field(pattern=rf"^{ANCHOR_ID_PATTERN}$")]], Field(min_length=1)]
]


def _describe_value_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, Mapping):
        return "a mapping"
    if isinstance(value, list):
        return "a list"
    return "null" if value is None else type(value).__name__


def _refuse_an_unusable_extra_item(value: Any) -> None:
    if value is None or isinstance(value, bool | Mapping | list):
        raise ValueError(
            f"an extra field must be a string, a number or a list of them, not {_describe_value_kind(value)}"
        )
    if isinstance(value, str) and not value.strip():
        raise ValueError("an extra field must not be blank")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("an extra field must be a finite number")


def _refuse_an_unusable_extra_field(value: Any) -> Any:
    if isinstance(value, list):
        if not value:
            raise ValueError("an extra field list must not be empty")
        items = cast("list[Any]", value)
        for item in items:
            _refuse_an_unusable_extra_item(item)
        return items
    _refuse_an_unusable_extra_item(value)
    return value


def fact_label(name: str) -> str:
    return name[:1].upper() + name[1:]


KNOWN_FIELD_NAMES: Final = ("status", "priority", "assignee", "due", "labels", "estimate")


class SectionFields(FrozenModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[  # pyright: ignore[reportIncompatibleVariableOverride]
        str, Annotated[FieldScalar | FieldList, BeforeValidator(_refuse_an_unusable_extra_field)]
    ] = Field(init=False)

    @property
    def extras(self) -> dict[str, FieldScalar | FieldList]:
        return cast("dict[str, FieldScalar | FieldList]", self.model_extra or {})

    @model_validator(mode="after")
    def _refuse_two_facts_under_one_label(self) -> "SectionFields":
        seen: dict[str, str] = {}
        sources = (
            *((name, "a known field", fact_label(name)) for name in KNOWN_FIELD_NAMES),
            *((name, "a link type", fact_label(name)) for name in self.links),
            *((name, "an extra field", name) for name in self.extras),
        )
        for name, kind, label in sources:
            if label in seen:
                raise ValueError(
                    f"'{name}' ({kind}) and {seen[label]} would both show as '{label}'; rename one of them"
                )
            seen[label] = f"'{name}' ({kind})"
        return self

    status: NonBlank | None = Field(
        default=None, description="Workflow state, shown as a chip (e.g. `In Progress`)."
    )
    priority: NonBlank | None = Field(default=None, description="Priority, shown as a chip (e.g. `High`).")
    assignee: NonBlank | None = Field(
        default=None, description="A person's key, shown as a person chip carrying the key."
    )
    due: IsoDate | None = Field(default=None, description="Due date, ISO `YYYY-MM-DD`.")
    labels: Annotated[list[NonBlank], Field(min_length=1)] | None = Field(
        default=None, description="Labels, each shown as a chip."
    )
    estimate: NonNegativeNumber | None = Field(default=None, description="Effort estimate as a number.")
    links: SectionLinks = Field(
        default_factory=SectionLinks,
        description="Links to other sections: a link type (`blocks`, `relates`, ...) mapped to the ids of "
        "the sections it points at. Every id must be the `id` of a section in this document.",
    )
