import re
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from typing_extensions import Self

from skaldr.frozen_model import FrozenModel
from skaldr.publish_block.target import JsonFields, Location, TargetBase
from skaldr.services import SlackService

SLACK_HOST = "slack.com"
TEAM = r"T[A-Z0-9]{2,}"
CONVERSATION = r"[CDG][A-Z0-9]{2,}"
CANVAS = r"F[A-Z0-9]{2,}"
CONVERSATION_ID = re.compile(CONVERSATION)
CANVAS_ID = re.compile(CANVAS)
CONVERSATION_PATH = re.compile(rf"/(?:archives|client/{TEAM})/({CONVERSATION})(?:/.*)?")
CANVAS_PATH = re.compile(rf"/docs/{TEAM}/({CANVAS})/?")


def _slack_id(reference: str, identifier: re.Pattern[str], path: re.Pattern[str]) -> str | None:
    candidate = reference.strip()
    if identifier.fullmatch(candidate):
        return candidate
    parsed = urlsplit(candidate)
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or not (host == SLACK_HOST or host.endswith(f".{SLACK_HOST}")):
        return None
    found = path.fullmatch(parsed.path)
    return None if found is None else found.group(1)


def slack_conversation_id(reference: str) -> str | None:
    return _slack_id(reference, CONVERSATION_ID, CONVERSATION_PATH)


def slack_canvas_id(reference: str) -> str | None:
    return _slack_id(reference, CANVAS_ID, CANVAS_PATH)


class SlackWhere(FrozenModel):
    conversation: str | None = Field(
        default=None,
        description="A Slack channel or DM id (C..., G... or D...), or a link to one, that skaldr lets read "
        "each canvas it creates and where it posts the link to the document's canvas, once, when it creates "
        "it; the document's canvas links each section canvas in its stamp. Left out: the canvases are shared "
        "with no one. Not part of the target's place, so changing it moves no canvas.",
    )
    canvas: str | None = Field(
        default=None,
        description="An existing Slack canvas id (F...), or a link to it, the document is written into, "
        "replacing its content.",
    )
    workspace: str | None = Field(
        default=None,
        description="The id or name of the signed-in Slack workspace to publish with; needed only when "
        "signed in to several. Part of the target's place, so naming another workspace is a move, which "
        "skaldr refuses.",
    )

    @field_validator("conversation")
    @classmethod
    def _conversation_as_its_id(cls, reference: str | None) -> str | None:
        if reference is None:
            return None
        conversation_id = slack_conversation_id(reference)
        if conversation_id is None:
            raise ValueError(
                f"'{reference}' is not a Slack channel or DM id (C..., G... or D...) or a link to one"
            )
        return conversation_id

    @field_validator("canvas")
    @classmethod
    def _canvas_as_its_id(cls, reference: str | None) -> str | None:
        if reference is None:
            return None
        canvas_id = slack_canvas_id(reference)
        if canvas_id is None:
            raise ValueError(f"'{reference}' is not a Slack canvas id (F...) or a link to one")
        return canvas_id

    @model_validator(mode="after")
    def _validate_one_place(self) -> Self:
        if self.conversation is not None and self.canvas is not None:
            raise ValueError("a slack target names at most one of `conversation` or `canvas`")
        return self


class SlackTarget(TargetBase):
    to: SlackService = Field(description="Publish to Slack canvases: `slack`.")
    where: SlackWhere = Field(
        default_factory=SlackWhere,
        description="The conversation each new canvas is shared with, or the canvas the document is written "
        "into. Left out: canvases shared with no one.",
    )

    @model_validator(mode="after")
    def _validate_no_fields(self) -> Self:
        for section_id, override in self.overrides.items():
            if override.fields:
                raise ValueError(
                    "a slack target sets no fields: a canvas holds a title and content only, so leave out "
                    f"`overrides.{section_id}.fields`"
                )
        return self

    def where_fields(self) -> JsonFields:
        return {}

    @classmethod
    def links_its_sections_from_the_document(cls) -> bool:
        return True

    def location_label(self) -> str:
        written_into = " (written into)" if self.where.canvas is not None else ""
        return f"{self.place_label()}{written_into}"

    def place_key(self) -> Location:
        return ("slack", self.where.canvas or "", self.where.workspace or "")

    def place_label(self) -> str:
        label = "slack canvases" if self.where.canvas is None else f"slack canvas {self.where.canvas}"
        return label if self.where.workspace is None else f"{label} in workspace {self.where.workspace}"
