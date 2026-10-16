from pydantic import JsonValue

from skaldr.models import Report, Section
from skaldr.publish_block.target import JsonFields


def _assignee_account_id(report: Report, person_key: str) -> str | None:
    person = report.meta.people.get(person_key)
    return None if person is None else person.jira


def jira_fields_of_section(report: Report, section: Section) -> JsonFields:
    authored = section.fields
    if authored is None:
        return {}
    fields: dict[str, JsonValue] = {}
    if authored.priority is not None:
        fields["priority"] = {"name": authored.priority}
    if authored.due is not None:
        fields["duedate"] = authored.due.isoformat()
    if authored.labels is not None:
        fields["labels"] = list(authored.labels)
    account_id = None if authored.assignee is None else _assignee_account_id(report, authored.assignee)
    if account_id is not None:
        fields["assignee"] = {"accountId": account_id}
    return fields
