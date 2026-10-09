import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from filelock import FileLock, Timeout
from pydantic import Field, ValidationError

from skaldr.errors import PublishError
from skaldr.frozen_model import FrozenModel
from skaldr.publish.content import ItemContent, Part, PartKind
from skaldr.publish_block.target import JsonFields
from skaldr.services import Service

STATE_FILE_SUFFIX = ".skaldr-state.json"
LOCK_FILE_SUFFIX = ".lock"


class WritingPart(FrozenModel):
    kind: PartKind
    key: str = ""

    @property
    def part(self) -> Part:
        return Part(self.kind, self.key)


class InFlightWrite(FrozenModel):
    parts: list[WritingPart]
    rendered: ItemContent


ItemOrigin = Literal["created", "adopted"]
Retirement = Literal["archive", "release"]


class PublishedItem(FrozenModel):
    item_id: str
    origin: ItemOrigin = "created"
    rendered: ItemContent
    remote: ItemContent
    marker: str | None = None
    shown_remote: str | None = None
    writing: InFlightWrite | None = None
    retiring: Retirement | None = None


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


class PendingCreate(FrozenModel):
    target: str
    section_id: str | None
    parent_id: str | None
    title: str
    into_id: str | None = None


class PublishState(FrozenModel):
    version: Literal[1] = 1
    doc_id: str
    targets: dict[str, PublishedTarget] = Field(default_factory=dict[str, PublishedTarget])
    pending_creates: list[PendingCreate] = Field(default_factory=list[PendingCreate])


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
            f"{path} is not a publish state skaldr can read; put back the copy you keep of it, since without "
            "it skaldr no longer knows which pages and issues it created"
        ) from exc
    if state.doc_id != doc_id:
        raise PublishError(
            f"{path} records the publishing of '{state.doc_id}', not '{doc_id}'. If you changed the "
            f"document's `doc_id`, change it back to '{state.doc_id}': skaldr knows its pages and issues by "
            "it, and a new doc_id would publish the document again as a new set of items"
        )
    return state


def refuse_an_unwritable_directory(path: Path) -> None:
    directory = path.parent
    if not os.access(directory, os.W_OK | os.X_OK):
        raise PublishError(
            f"skaldr keeps the publish state next to the document, and {directory} is not writable; make "
            "it writable, or move the document somewhere it is"
        )


@contextmanager
def held_state_lock(path: Path, document: Path, command: str) -> Generator[None, None, None]:
    refuse_an_unwritable_directory(path)
    lock = FileLock(str(path) + LOCK_FILE_SUFFIX)
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise PublishError(
            f"`skaldr {command}` cannot run on {document}: another skaldr run holds {lock.lock_file}; wait "
            "for it to finish, then run this again"
        ) from exc
    try:
        yield
    finally:
        lock.release()


def save_state(path: Path, state: PublishState) -> None:
    refuse_an_unwritable_directory(path)
    encoded = (state.model_dump_json(indent=2) + "\n").encode("utf-8")
    descriptor, staged = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as staging:
            staging.write(encoded)
            staging.flush()
            os.fsync(staging.fileno())
        Path(staged).replace(path)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise
    _sync_the_directory(path.parent)


def _sync_the_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
