from collections import Counter
from collections.abc import Sequence
from typing import Annotated

from pydantic import Field

from skaldr.frozen_model import FrozenModel
from skaldr.publish.jira import JiraTarget
from skaldr.publish.notion import NotionTarget

DOC_ID_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
NOT_A_SECTION = "which is not the id of a top-level section (a section is named by its `id:`)"

PublishTarget = Annotated[NotionTarget | JiraTarget, Field(discriminator="to")]


class Publish(FrozenModel):
    doc_id: str = Field(
        min_length=2,
        pattern=rf"^{DOC_ID_PATTERN}$",
        description="The document's identity in every target, stamped on each page and issue it creates: "
        "at least two characters, lowercase letters and digits joined by single hyphens.",
    )
    targets: list[PublishTarget] = Field(min_length=1, description="Where the document publishes.")


def _repeated(ids: Sequence[str]) -> list[str]:
    return [section_id for section_id, count in Counter(ids).items() if count > 1]


def _target_errors(target_label: str, target: NotionTarget | JiraTarget, section_ids: set[str]) -> list[str]:
    chosen = target.from_sections or []
    errors = [
        f"{target_label} lists '{section_id}' more than once in `from`" for section_id in _repeated(chosen)
    ]
    errors += [
        f"{target_label} is built from '{section_id}', {NOT_A_SECTION}"
        for section_id in chosen
        if section_id not in section_ids
    ]
    errors += [
        f"{target_label} lists '{section_id}' more than once in `split`"
        for section_id in _repeated(target.split)
    ]
    for section_id in dict.fromkeys(target.split):
        if section_id not in section_ids:
            errors.append(f"{target_label} splits on '{section_id}', {NOT_A_SECTION}")
        elif target.from_sections is not None and section_id not in target.from_sections:
            errors.append(f"{target_label} splits on '{section_id}', which its `from` list leaves out")
    errors += [
        f"{target_label} overrides '{section_id}', which is not one of its split sections"
        for section_id in target.overrides
        if section_id not in target.split
    ]
    return errors


def section_choice_errors(publish: Publish, section_ids: Sequence[str]) -> list[str]:
    errors = [
        f"section id '{section_id}' names more than one top-level section"
        for section_id in _repeated(section_ids)
    ]
    known = set(section_ids)
    for position, target in enumerate(publish.targets, start=1):
        errors += _target_errors(f"publish target {position} ({target.to})", target, known)
    first_target_at: dict[str, int] = {}
    for position, target in enumerate(publish.targets, start=1):
        location = target.location_key()
        if location in first_target_at:
            errors.append(
                f"publish targets {first_target_at[location]} and {position} both write to {location}"
            )
        else:
            first_target_at[location] = position
    return errors
