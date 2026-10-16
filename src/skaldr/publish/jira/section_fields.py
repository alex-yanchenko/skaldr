from pydantic import JsonValue

from skaldr.models import Report, Section, SectionFields
from skaldr.publish.connector import NO_SECTION_DEFAULTS, SectionDefaults
from skaldr.publish_block import JiraTarget, TargetBase
from skaldr.publish_block.target import JsonFields


def _assignee_refusals(report: Report, authored: SectionFields, authored_path: str) -> tuple[str, ...]:
    person_key = authored.assignee
    if person_key is None:
        return ()
    person = report.meta.people.get(person_key)
    if person is not None and person.jira is not None:
        return ()
    return (
        f"{authored_path}.assignee is '{person_key}', but that person has no jira account id in "
        f"meta.people; add one under meta.people.{person_key}.jira, or remove the assignee",
    )


def _label_refusals(authored: SectionFields, authored_path: str) -> tuple[str, ...]:
    return tuple(
        f"{authored_path}.labels.{position} is '{label}', but Jira labels cannot hold spaces; "
        f"write it with hyphens, such as '{'-'.join(label.split())}'"
        for position, label in enumerate(authored.labels or [])
        if any(character.isspace() for character in label)
    )


def _mapped_fields(report: Report, authored: SectionFields) -> JsonFields:
    values: dict[str, JsonValue] = {}
    if authored.priority is not None:
        values["priority"] = {"name": authored.priority}
    if authored.due is not None:
        values["duedate"] = authored.due.isoformat()
    if authored.labels is not None:
        values["labels"] = list(authored.labels)
    person = None if authored.assignee is None else report.meta.people.get(authored.assignee)
    if person is not None and person.jira is not None:
        values["assignee"] = {"accountId": person.jira}
    return values


def jira_section_defaults(
    report: Report, section: Section, source_index: int, target: TargetBase
) -> SectionDefaults:
    authored = section.fields
    if authored is None or not isinstance(target, JiraTarget) or not target.where.fields_from_sections:
        return NO_SECTION_DEFAULTS
    authored_path = f"blocks[{source_index}].fields"
    return SectionDefaults(
        _mapped_fields(report, authored),
        authored_path,
        (*_label_refusals(authored, authored_path), *_assignee_refusals(report, authored, authored_path)),
    )
