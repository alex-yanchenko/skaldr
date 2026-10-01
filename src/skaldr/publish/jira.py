from typing import Annotated, Literal

from pydantic import Field, JsonValue, StringConstraints, model_validator

from skaldr.frozen_model import FrozenModel
from skaldr.publish.target import Fields, PublishTargetBase

JIRA_PROJECT_KEY_PATTERN = r"[A-Z][A-Z0-9_]+"
JIRA_ISSUE_KEY_PATTERN = rf"{JIRA_PROJECT_KEY_PATTERN}-[1-9][0-9]*"


class JiraWhere(FrozenModel):
    project: str = Field(
        pattern=rf"^{JIRA_PROJECT_KEY_PATTERN}$", description="The Jira project key, e.g. PLAN."
    )
    issue_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        description="The issue type each created issue gets, e.g. Task."
    )
    parent: str | None = Field(
        default=None,
        pattern=rf"^{JIRA_ISSUE_KEY_PATTERN}$",
        description="An existing issue key the document's issue is created under, e.g. PLAN-100.",
    )
    fields: Fields = Field(
        default_factory=dict[str, JsonValue],
        description="Field values for every created issue: labels, priority, components, custom fields.",
    )


class JiraTarget(PublishTargetBase):
    to: Literal["jira"] = Field(description="Publish to Jira.")
    where: JiraWhere = Field(description="The Jira project, issue type and optional parent issue.")

    @model_validator(mode="after")
    def _archive_only(self) -> "JiraTarget":
        if self.removed == "delete":
            raise ValueError(
                "a jira target cannot use `removed: delete`: Jira issues are archived, never deleted"
            )
        return self

    def location_key(self) -> str:
        return f"jira project {self.where.project} under {self.where.parent or 'no parent'}"
