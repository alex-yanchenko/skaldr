import json
import os
import re
from pathlib import Path

import pytest

from skaldr.errors import PublishError
from skaldr.publish.content import ItemContent
from skaldr.publish.state import (
    PublishedItem,
    PublishedTarget,
    PublishState,
    held_state_lock,
    load_state,
    save_state,
    state_path_for,
)
from tests.factories.publish_factory import DOC_ID, OTHER_DOC_ID, TARGET_LABEL


def _state() -> PublishState:
    content = ItemContent(
        title="Garden handbook", sections={"blocks[0]": "Welcome.\n"}, fields={"labels": ["a"]}
    )
    return PublishState(
        doc_id=DOC_ID,
        targets={
            TARGET_LABEL: PublishedTarget(
                service="notion",
                target={"to": "notion", "where": {"parent_page": "0123456789abcdef0123456789abcdef"}},
                document=PublishedItem(item_id="page-1", rendered=content, remote=content, marker="7"),
            )
        },
    )


@pytest.mark.parametrize(
    ("document", "state"),
    [
        pytest.param("plans/garden.yaml", "plans/garden.skaldr-state.json", id="yaml"),
        pytest.param("garden.yml", "garden.skaldr-state.json", id="yml"),
        pytest.param("garden.skaldr.yaml", "garden.skaldr.skaldr-state.json", id="two-suffixes"),
    ],
)
def test_the_state_file_sits_next_to_the_document(document: str, state: str) -> None:
    assert state_path_for(Path(document)) == Path(state)


def test_a_document_never_published_starts_from_an_empty_state(tmp_path: Path) -> None:
    assert load_state(tmp_path / "garden.skaldr-state.json", DOC_ID) == PublishState(doc_id=DOC_ID)


def test_a_saved_state_loads_back_whole(tmp_path: Path) -> None:
    path = tmp_path / "garden.skaldr-state.json"

    save_state(path, _state())

    assert (load_state(path, DOC_ID), json.loads(path.read_text(encoding="utf-8"))["version"]) == (
        _state(),
        1,
    )


def test_a_state_file_of_another_doc_id_is_refused_naming_a_changed_doc_id_as_the_likely_cause(
    tmp_path: Path,
) -> None:
    path = tmp_path / "garden.skaldr-state.json"
    save_state(path, _state().model_copy(update={"doc_id": OTHER_DOC_ID}))
    expected = (
        f"{path} records the publishing of 'kitchen-rota', not 'garden-handbook'. If you changed the "
        "document's `doc_id`, change it back to 'kitchen-rota': skaldr knows its pages and issues by it, and "
        "a new doc_id would publish the document again as a new set of items"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        load_state(path, DOC_ID)


@pytest.mark.parametrize(
    "text", [pytest.param("{", id="not-json"), pytest.param('{"version": 2}', id="wrong-shape")]
)
def test_an_unreadable_state_file_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "garden.skaldr-state.json"
    path.write_text(text, encoding="utf-8")
    expected = (
        f"{path} is not a publish state skaldr can read; put back the copy you keep of it, since without it "
        "skaldr no longer knows which pages and issues it created"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        load_state(path, DOC_ID)


def test_saving_writes_a_synced_file_beside_the_state_and_then_replaces_the_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "garden.skaldr-state.json"
    save_state(path, PublishState(doc_id=DOC_ID))
    order: list[str] = []
    real_fsync, real_replace = os.fsync, Path.replace

    def fsync(descriptor: int) -> None:
        order.append("fsync")
        real_fsync(descriptor)

    def replace(staged: Path, target: Path) -> Path:
        order.append(f"replace {staged.parent == path.parent} {staged.name.startswith('.garden')}")
        return real_replace(staged, target)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(Path, "replace", replace)

    save_state(path, _state())

    assert (order, load_state(path, DOC_ID), sorted(entry.name for entry in tmp_path.iterdir())) == (
        ["fsync", "replace True True"],
        _state(),
        ["garden.skaldr-state.json"],
    )


def test_saving_next_to_a_document_in_an_unwritable_folder_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "plans"
    folder.mkdir()
    folder.chmod(0o555)
    expected = (
        f"skaldr keeps the publish state next to the document, and {folder} is not writable; make it "
        "writable, or move the document somewhere it is"
    )

    try:
        with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
            save_state(folder / "garden.skaldr-state.json", _state())
    finally:
        folder.chmod(0o755)


def test_a_second_publish_of_the_same_document_is_refused_while_the_first_holds_the_lock(
    tmp_path: Path,
) -> None:
    path = tmp_path / "garden.skaldr-state.json"
    document = tmp_path / "garden.yaml"
    expected = (
        f"another skaldr publish of {document} is running and holds {path}.lock; wait for it to finish, then "
        "run this again"
    )

    with (
        held_state_lock(path, document),
        pytest.raises(PublishError, match=f"^{re.escape(expected)}$"),
        held_state_lock(path, document),
    ):
        pass
