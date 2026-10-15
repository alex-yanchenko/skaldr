import re
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from typing_extensions import Self

from skaldr.frozen_model import FrozenModel
from skaldr.publish_block.target import JsonFields, Location, TargetBase
from skaldr.services import SlackService

SLACK_HOST = "slack.com"
CONVERSATION_ID = re.compile(r"[CDG][A-Z0-9]{2,}")
CANVAS_ID = re.compile(r"F[A-Z0-9]{2,}")


def _is_slack_host(host: str) -> bool:
    return host == SLACK_HOST or host.endswith(f".{SLACK_HOST}")


def _slack_id(reference: str, pattern: re.Pattern[str]) -> str | None:
    candidate = reference.strip()
    if pattern.fullmatch(candidate):
        return candidate
    parsed = urlsplit(candidate)
    if parsed.scheme not in ("http", "https") or not _is_slack_host(parsed.hostname or ""):
        return None
    return next((segment for segment in parsed.path.split("/") if pattern.fullmatch(segment)), None)


def slack_conversation_id(reference: str) -> str | None:
    return _slack_id(reference, CONVERSATION_ID)


def slack_canvas_id(reference: str) -> str | None:
    return _slack_id(reference, CANVAS_ID)


class SlackWhere(FrozenModel):
    conversation: str | None = Field(
        default=None,
        description="A Slack channel or DM id (C..., G... or D...), or a link to one, where skaldr posts the "
        "link to each canvas it creates, once, when it creates it. Left out: the canvases are linked "
        "nowhere.",
    )
    canvas: str | None = Field(
        default=None,
        description="An existing Slack canvas id (F...), or a link to it, the document is written into, "
        "replacing its content.",
    )
    workspace: str | None = Field(
        default=None,
        description="The id or name of the signed-in Slack workspace to publish with; needed only when "
        "signed in to several. Not part of the target's place.",
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
        description="The conversation each new canvas is linked in, or the canvas the document is written "
        "into. Left out: canvases linked nowhere.",
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

    def location_label(self) -> str:
        written_into = " (written into)" if self.where.canvas is not None else ""
        return f"{self.place_label()}{written_into}"

    def place_key(self) -> Location:
        return ("slack", self.where.conversation or "", self.where.canvas or "")

    def place_label(self) -> str:
        if self.where.canvas is not None:
            return f"slack canvas {self.where.canvas}"
        if self.where.conversation is not None:
            return f"slack conversation {self.where.conversation}"
        return "slack without a conversation"
