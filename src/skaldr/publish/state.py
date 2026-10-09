from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from skaldr.errors import PublishError
from skaldr.frozen_model import FrozenModel
from skaldr.publish.content import ItemContent
from skaldr.publish_block.target import JsonFields
from skaldr.replace_file import replace_file
from skaldr.services import Service

STATE_FILE_SUFFIX = ".skaldr-state.json"


class PublishedItem(FrozenModel):
    item_id: str
    rendered: ItemContent
    remote: ItemContent
    marker: str | None = None
    shown_remote: str | None = None


class PublishedTarget(FrozenModel):
    service: Service
    target: JsonFields
    document: PublishedItem | None = None
    sections: dict[str, PublishedItem] = Field(default_factory=dict[str, PublishedItem])

    def held_items(self) -> list[tuple[str | None, PublishedItem]]:
        document: list[tuple[str | None, PublishedItem]] = (
            [] if self.document is None else [(None, self.document)]
        )
        return [*document, *self.sections.items()]


class PublishState(FrozenModel):
    version: Literal[1] = 1
    doc_id: str
    targets: dict[str, PublishedTarget] = Field(default_factory=dict[str, PublishedTarget])


def state_path_for(document_path: Path) -> Path:
    return document_path.with_name(document_path.stem + STATE_FILE_SUFFIX)


def load_state(path: Path, doc_id: str) -> PublishState:
    try:
        text = path.read_bytes()
    except FileNotFoundError:
        return PublishState(doc_id=doc_id)
    try:
        state = PublishState.model_validate_json(text)
    except ValidationError as exc:
        raise PublishError(
            f"{path} is not a publish state skaldr can read; restore it from version control or a backup, "
            "since without it skaldr no longer knows which pages and issues it created"
        ) from exc
    if state.doc_id != doc_id:
        raise PublishError(
            f"{path} records the publishing of '{state.doc_id}', not '{doc_id}'; each document keeps its own "
            "state file next to it, so rename one of the two documents' files or restore the right state file"
        )
    return state


def save_state(path: Path, state: PublishState) -> None:
    replace_file(path, state.model_dump_json(indent=2) + "\n")
