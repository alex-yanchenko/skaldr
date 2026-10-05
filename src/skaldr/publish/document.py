from collections import Counter
from collections.abc import Sequence
from typing import Annotated

from pydantic import Field, model_validator

from skaldr.frozen_model import FrozenModel
from skaldr.patterns import SLUG_PATTERN
from skaldr.publish.jira import JiraTarget
from skaldr.publish.notion import NotionTarget
from skaldr.publish.target import Location, TargetBase

NOT_A_SECTION = "which is not the id of a top-level section (a section is named by its `id:`)"

PublishTarget = Annotated[NotionTarget | JiraTarget, Field(discriminator="to")]


class Publish(FrozenModel):
    doc_id: str = Field(
        min_length=2,
        pattern=rf"^{SLUG_PATTERN}$",
        description="The document's identity in every target, stamped on each page and issue it creates: "
        "at least two characters, lowercase letters and digits joined by single hyphens.",
    )
    targets: list[PublishTarget] = Field(
        min_length=1,
        description="One entry per place the document publishes to; each is built from the document on "
        "its own.",
    )

    @model_validator(mode="after")
    def _validate_distinct_locations(self) -> "Publish":
        first_target_at: dict[Location, int] = {}
        for position, target in enumerate(self.targets, start=1):
            location = target.location_key()
            if location in first_target_at:
                raise ValueError(
                    f"publish targets {first_target_at[location]} and {position} both write to "
                    f"{target.location_label()}"
                )
            first_target_at[location] = position
        return self


def _duplicates(ids: Sequence[str]) -> list[str]:
    return [section_id for section_id, count in Counter(ids).items() if count > 1]


def _from_errors(target_label: str, target: TargetBase, known_section_ids: set[str]) -> list[str]:
    chosen = target.from_sections or []
    return [
        *(
            f"{target_label} lists '{section_id}' more than once in `from`"
            for section_id in _duplicates(chosen)
        ),
        *(
            f"{target_label} is built from '{section_id}', {NOT_A_SECTION}"
            for section_id in chosen
            if section_id not in known_section_ids
        ),
    ]


def _split_error(
    target_label: str, target: TargetBase, section_id: str, known_section_ids: set[str]
) -> str | None:
    if section_id not in known_section_ids:
        return f"{target_label} splits on '{section_id}', {NOT_A_SECTION}"
    if target.from_sections is not None and section_id not in target.from_sections:
        return f"{target_label} splits on '{section_id}', which its `from` list leaves out"
    return None


def _split_errors(target_label: str, target: TargetBase, known_section_ids: set[str]) -> list[str]:
    unique_errors = (
        _split_error(target_label, target, section_id, known_section_ids)
        for section_id in dict.fromkeys(target.split)
    )
    return [
        *(
            f"{target_label} lists '{section_id}' more than once in `split`"
            for section_id in _duplicates(target.split)
        ),
        *(error for error in unique_errors if error is not None),
    ]


def _override_errors(target_label: str, target: TargetBase) -> list[str]:
    return [
        f"{target_label} overrides '{section_id}', which is not one of its split sections"
        for section_id in target.overrides
        if section_id not in target.split
    ]


def section_choice_errors(publish: Publish, section_ids: Sequence[str]) -> list[str]:
    known_section_ids = set(section_ids)
    errors: list[str] = []
    for position, target in enumerate(publish.targets, start=1):
        target_label = f"publish target {position} ({target.to})"
        errors += _from_errors(target_label, target, known_section_ids)
        errors += _split_errors(target_label, target, known_section_ids)
        errors += _override_errors(target_label, target)
    return errors
