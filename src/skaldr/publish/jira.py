from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from skaldr.frozen_model import FrozenModel
from skaldr.publish.target import JsonFields, Location, TargetBase

JIRA_PROJECT_KEY_PATTERN = r"[A-Z][A-Z0-9_]+"
JIRA_ISSUE_KEY_PATTERN = rf"{JIRA_PROJECT_KEY_PATTERN}-[1-9][0-9]*"


class JiraWhere(FrozenModel):
    project: str = Field(
        pattern=rf"^{JIRA_PROJECT_KEY_PATTERN}$",
        description="The Jira project key: an uppercase letter, then uppercase letters, digits or `_`, "
        "e.g. PLAN.",
    )
    issue_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        description="The issue type each created issue gets, e.g. Task. Not blank."
    )
    parent: str | None = Field(
        default=None,
        pattern=rf"^{JIRA_ISSUE_KEY_PATTERN}$",
        description="An existing issue key the document's issue is created under, e.g. PLAN-100.",
    )
    fields: JsonFields = Field(
        default_factory=JsonFields,
        description="Field values for every created issue (labels, priority, components, custom fields); "
        "`overrides` changes them for one item.",
    )


class JiraTarget(TargetBase):
    to: Literal["jira"] = Field(description="Publish to Jira: `jira`.")
    where: JiraWhere = Field(description="The Jira project, issue type and optional parent issue.")

    def location_key(self) -> Location:
        return ("jira", self.where.project, self.where.parent or "")

    def location_label(self) -> str:
        return f"jira project {self.where.project} under {self.where.parent or 'no parent issue'}"
