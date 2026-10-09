from typing import Annotated, Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Discriminator, Field, JsonValue, Tag

READ_PROPERTY_TYPES = (
    "title",
    "rich_text",
    "number",
    "select",
    "status",
    "multi_select",
    "date",
    "checkbox",
    "url",
    "email",
    "phone_number",
    "people",
    "relation",
    "files",
)
OTHER_PROPERTY = "other"


class NotionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class PartialUser(NotionResponse):
    id: str


class User(NotionResponse):
    object: Literal["user"]
    id: str
    type: Literal["person", "bot"] | None = None
    name: str | None = None


class RichTextItem(NotionResponse):
    plain_text: str


class SelectOption(NotionResponse):
    name: str


class DateRange(NotionResponse):
    start: str
    end: str | None = None


class Reference(NotionResponse):
    id: str


class NamedFile(NotionResponse):
    name: str


class TitleValue(NotionResponse):
    type: Literal["title"]
    title: list[RichTextItem]


class RichTextValue(NotionResponse):
    type: Literal["rich_text"]
    rich_text: list[RichTextItem]


class NumberValue(NotionResponse):
    type: Literal["number"]
    number: int | float | None


class SelectValue(NotionResponse):
    type: Literal["select"]
    select: SelectOption | None


class StatusValue(NotionResponse):
    type: Literal["status"]
    status: SelectOption | None


class MultiSelectValue(NotionResponse):
    type: Literal["multi_select"]
    multi_select: list[SelectOption]


class DateValue(NotionResponse):
    type: Literal["date"]
    date: DateRange | None


class CheckboxValue(NotionResponse):
    type: Literal["checkbox"]
    checkbox: bool


class UrlValue(NotionResponse):
    type: Literal["url"]
    url: str | None


class EmailValue(NotionResponse):
    type: Literal["email"]
    email: str | None


class PhoneNumberValue(NotionResponse):
    type: Literal["phone_number"]
    phone_number: str | None


class PeopleValue(NotionResponse):
    type: Literal["people"]
    people: list[Reference]


class RelationValue(NotionResponse):
    type: Literal["relation"]
    relation: list[Reference]


class FilesValue(NotionResponse):
    type: Literal["files"]
    files: list[NamedFile]


class OtherValue(NotionResponse):
    type: str


def _property_kind(value: object) -> str:
    kind: object = (
        cast("dict[str, object]", value).get("type")
        if isinstance(value, dict)
        else getattr(value, "type", None)
    )
    return kind if isinstance(kind, str) and kind in READ_PROPERTY_TYPES else OTHER_PROPERTY


PropertyValue = Annotated[
    Annotated[TitleValue, Tag("title")]
    | Annotated[RichTextValue, Tag("rich_text")]
    | Annotated[NumberValue, Tag("number")]
    | Annotated[SelectValue, Tag("select")]
    | Annotated[StatusValue, Tag("status")]
    | Annotated[MultiSelectValue, Tag("multi_select")]
    | Annotated[DateValue, Tag("date")]
    | Annotated[CheckboxValue, Tag("checkbox")]
    | Annotated[UrlValue, Tag("url")]
    | Annotated[EmailValue, Tag("email")]
    | Annotated[PhoneNumberValue, Tag("phone_number")]
    | Annotated[PeopleValue, Tag("people")]
    | Annotated[RelationValue, Tag("relation")]
    | Annotated[FilesValue, Tag("files")]
    | Annotated[OtherValue, Tag(OTHER_PROPERTY)],
    Discriminator(_property_kind),
]


class Page(NotionResponse):
    object: Literal["page"]
    id: str
    last_edited_time: AwareDatetime
    last_edited_by: PartialUser
    in_trash: bool
    properties: dict[str, PropertyValue]


class PageMarkdown(NotionResponse):
    object: Literal["page_markdown"]
    id: str
    markdown: str
    truncated: bool
    unknown_block_ids: list[str] = Field(default_factory=list[str])


class Block(NotionResponse):
    object: Literal["block"]
    id: str
    type: str
    in_trash: bool = False


class DataSourceReference(NotionResponse):
    id: str
    name: str


class Database(NotionResponse):
    object: Literal["database"]
    id: str
    data_sources: list[DataSourceReference]


class PropertySchema(NotionResponse):
    id: str
    type: str


class DataSource(NotionResponse):
    object: Literal["data_source"]
    id: str
    properties: dict[str, PropertySchema]


class ErrorBody(NotionResponse):
    object: Literal["error"] = "error"
    status: int | None = None
    code: str = "unknown"
    message: str = ""


class PendingTask(NotionResponse):
    object: Literal["async_task"]
    id: str
    status: Literal["queued", "running", "retrying"]
    poll_after_seconds: int = Field(ge=0)


class SucceededTask(NotionResponse):
    object: Literal["async_task"]
    id: str
    status: Literal["succeeded"]
    result: dict[str, JsonValue]


class FailedTask(NotionResponse):
    object: Literal["async_task"]
    id: str
    status: Literal["failed"]
    error: ErrorBody


AsyncTask = Annotated[PendingTask | SucceededTask | FailedTask, Field(discriminator="status")]
