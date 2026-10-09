from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from skaldr.auth.site import normalise_site
from skaldr.errors import AuthError
from skaldr.frozen_model import FrozenModel
from skaldr.publish_block.target import JsonFields, Location, TargetBase
from skaldr.services import JiraService

JIRA_PROJECT_KEY_PATTERN = r"[A-Z][A-Z0-9_]+"
JIRA_ISSUE_KEY_PATTERN = rf"{JIRA_PROJECT_KEY_PATTERN}-[1-9][0-9]*"
FIELDS_SKALDR_SETS = frozenset({"summary", "description", "project", "issuetype", "parent", "status"})


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
    site: str | None = Field(
        default=None,
        description="The https URL of the signed-in Jira site this target publishes to, e.g. "
        "https://example.atlassian.net. Needed only when you are signed in to several sites. Part of the "
        "target's place: changing it is a move.",
    )
    fields: JsonFields = Field(
        default_factory=JsonFields,
        description="Field values for every created issue (labels, priority, components, custom fields); "
        "`overrides` changes them for one item.",
    )

    @field_validator("site")
    @classmethod
    def _normalise_site_like_skaldr_auth(cls, site: str | None) -> str | None:
        if site is None:
            return None
        try:
            return normalise_site(site)
        except AuthError as exc:
            raise ValueError(str(exc)) from exc


def _set_by_skaldr(fields: JsonFields, place: str) -> str | None:
    taken = [name for name in sorted(fields) if name in FIELDS_SKALDR_SETS]
    if not taken:
        return None
    named = ", ".join(f"`{name}`" for name in taken)
    return (
        f"a jira target cannot set {named} in `{place}`; skaldr sets summary, description, project, "
        "issuetype and parent itself, and Jira changes status only through a transition"
    )


class JiraTarget(TargetBase):
    to: JiraService = Field(description="Publish to Jira: `jira`.")
    where: JiraWhere = Field(description="The Jira project, issue type and optional parent issue.")

    @model_validator(mode="after")
    def _validate_fields_left_to_skaldr(self) -> "JiraTarget":
        places = [
            (self.where.fields, "where.fields"),
            *(
                (override.fields, f"overrides.{section_id}.fields")
                for section_id, override in self.overrides.items()
            ),
        ]
        for fields, place in places:
            refusal = _set_by_skaldr(fields, place)
            if refusal is not None:
                raise ValueError(refusal)
        return self

    def where_fields(self) -> JsonFields:
        return self.where.fields

    def place_key(self) -> Location:
        return ("jira", self.where.project, self.where.parent or "", self.where.site or "")

    def place_label(self) -> str:
        label = f"jira project {self.where.project} under {self.where.parent or 'no parent issue'}"
        return label if self.where.site is None else f"{label} on {self.where.site}"
