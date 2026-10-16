from pydantic import JsonValue

from skaldr.models import Report, Section, SectionFields
from skaldr.publish.connector import NO_SECTION_DEFAULTS, SectionDefaults
from skaldr.publish_block import JiraTarget, TargetBase
from skaldr.publish_block.target import JsonFields


def _unmapped_assignee_warning(report: Report, person_key: str) -> str:
    reason = "has no jira id" if person_key in report.meta.people else "is not"
    return f"assignee '{person_key}' {reason} in meta.people; the issue's assignee is left as it is"


def _label_refusals(labels: list[str], authored_path: str) -> tuple[str, ...]:
    return tuple(
        f"{authored_path}.labels.{position} is '{label}', but Jira labels cannot hold spaces; "
        f"write it with hyphens, such as '{'-'.join(label.split())}'"
        for position, label in enumerate(labels)
        if any(character.isspace() for character in label)
    )


def _mapped_fields(authored: SectionFields, authored_path: str) -> tuple[JsonFields, dict[str, str]]:
    values: dict[str, JsonValue] = {}
    sources: dict[str, str] = {}
    if authored.priority is not None:
        values["priority"] = {"name": authored.priority}
        sources["priority"] = f"{authored_path}.priority"
    if authored.due is not None:
        values["duedate"] = authored.due.isoformat()
        sources["duedate"] = f"{authored_path}.due"
    if authored.labels is not None:
        values["labels"] = list(authored.labels)
        sources["labels"] = f"{authored_path}.labels"
    return values, sources


def jira_section_defaults(
    report: Report, section: Section, source_index: int, target: TargetBase
) -> SectionDefaults:
    authored = section.fields
    if authored is None or not isinstance(target, JiraTarget) or not target.where.fields_from_sections:
        return NO_SECTION_DEFAULTS
    authored_path = f"blocks[{source_index}].fields"
    values, sources = _mapped_fields(authored, authored_path)
    refusals = () if authored.labels is None else _label_refusals(authored.labels, authored_path)
    if authored.assignee is None:
        return SectionDefaults(values, sources, refusals=refusals)
    person = report.meta.people.get(authored.assignee)
    if person is None or person.jira is None:
        return SectionDefaults(
            values,
            sources,
            warnings=(_unmapped_assignee_warning(report, authored.assignee),),
            refusals=refusals,
            left_alone=("assignee",),
        )
    return SectionDefaults(
        {**values, "assignee": {"accountId": person.jira}},
        {**sources, "assignee": f"{authored_path}.assignee"},
        refusals=refusals,
    )
