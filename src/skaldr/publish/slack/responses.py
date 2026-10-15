from pydantic import BaseModel, ConfigDict


class SlackResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    ok: bool
    error: str | None = None
    needed: str | None = None


class CreatedCanvas(SlackResponse):
    canvas_id: str


class CanvasContent(SlackResponse):
    content: str


class Identity(SlackResponse):
    url: str | None = None
    team_id: str | None = None
