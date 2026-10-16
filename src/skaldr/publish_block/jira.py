from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator
from typing_extensions import Self

from skaldr.auth.site import normalise_site
from skaldr.errors import AuthError
from skaldr.frozen_model import FrozenModel
from skaldr.publish_block.target import JsonFields, Location, TargetBase
from skaldr.services import JiraService

JIRA_PROJECT_KEY_PATTERN = r"[A-Z][A-Z0-9_]+"
JIRA_ISSUE_KEY_PATTERN = rf"{JIRA_PROJECT_KEY_PATTERN}-[1-9][0-9]*"
SUMMARY_FIELD = "summary"
DESCRIPTION_FIELD = "description"
PROJECT_FIELD = "project"
ISSUE_TYPE_FIELD = "issuetype"
PARENT_FIELD = "parent"
STATUS_FIELD = "status"
FIELDS_SKALDR_SETS_ITSELF = (SUMMARY_FIELD, DESCRIPTION_FIELD, PROJECT_FIELD, ISSUE_TYPE_FIELD, PARENT_FIELD)
SKALDR_OWNED_FIELDS = frozenset({*FIELDS_SKALDR_SETS_ITSELF, STATUS_FIELD})


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

    fields_from_sections: bool = Field(
        default=False,
        description="Whether each split section's own `fields` (priority, due, labels, assignee) set the "
        "Jira fields of its issue, under this target's `fields` and the section's `overrides`. Off by "
        "default; turning it on makes skaldr own those fields on every split issue.",
    )

    @field_validator("site")
    @classmethod
    def _site_as_a_jira_cloud_https_origin(cls, site: str | None) -> str | None:
        if site is None:
            return None
        try:
            return normalise_site(site)
        except AuthError as exc:
            raise ValueError(str(exc)) from exc


def _in_words(names: tuple[str, ...]) -> str:
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _refusal_for_owned_fields(fields: JsonFields, place: str) -> str | None:
    taken = sorted(fields.keys() & SKALDR_OWNED_FIELDS)
    if not taken:
        return None
    named = ", ".join(f"`{name}`" for name in taken)
    return (
        f"a jira target cannot set {named} in `{place}`; skaldr sets {_in_words(FIELDS_SKALDR_SETS_ITSELF)} "
        f"itself, and Jira changes {STATUS_FIELD} only through a transition"
    )


class JiraTarget(TargetBase):
    to: JiraService = Field(description="Publish to Jira: `jira`.")
    where: JiraWhere = Field(description="The Jira project, issue type and optional parent issue.")

    @model_validator(mode="after")
    def _validate_fields_left_to_skaldr(self) -> Self:
        places = [
            (self.where.fields, "where.fields"),
            *(
                (override.fields, f"overrides.{section_id}.fields")
                for section_id, override in self.overrides.items()
            ),
        ]
        for fields, place in places:
            refusal = _refusal_for_owned_fields(fields, place)
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
