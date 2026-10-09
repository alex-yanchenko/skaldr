from pydantic import BaseModel, ConfigDict, Field, JsonValue

DONE_CATEGORY = "done"


class JiraModel(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)


class CreatedIssue(JiraModel):
    key: str


class Issue(JiraModel):
    key: str
    fields: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class StatusCategory(JiraModel):
    key: str


class Status(JiraModel):
    name: str
    status_category: StatusCategory = Field(alias="statusCategory")

    @property
    def is_done(self) -> bool:
        return self.status_category.key == DONE_CATEGORY


class UserDetails(JiraModel):
    account_id: str | None = Field(default=None, alias="accountId")
    display_name: str | None = Field(default=None, alias="displayName")


class ChangeDetails(JiraModel):
    field: str
    field_id: str | None = Field(default=None, alias="fieldId")

    @property
    def names(self) -> frozenset[str]:
        return frozenset({self.field} if self.field_id is None else {self.field, self.field_id})


class Changelog(JiraModel):
    id: str = Field(pattern=r"^[0-9]+$")
    author: UserDetails | None = None
    created: str | None = None
    items: list[ChangeDetails] = Field(default_factory=list[ChangeDetails])

    @property
    def number(self) -> int:
        return int(self.id)


class ChangelogPage(JiraModel):
    start_at: int = Field(alias="startAt")
    total: int | None = None
    is_last: bool | None = Field(default=None, alias="isLast")
    values: list[Changelog] = Field(default_factory=list[Changelog])


class Transition(JiraModel):
    id: str
    to: Status


class Transitions(JiraModel):
    transitions: list[Transition] = Field(default_factory=list[Transition])


class EntityProperty(JiraModel):
    key: str
    value: JsonValue


class JiraUser(JiraModel):
    account_id: str = Field(alias="accountId")
