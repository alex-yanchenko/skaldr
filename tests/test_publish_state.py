import json
import re
from pathlib import Path

import pytest

from skaldr.errors import PublishError
from skaldr.publish.content import ItemContent
from skaldr.publish.state import (
    PublishedItem,
    PublishedTarget,
    PublishState,
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


def test_a_state_file_of_another_document_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "garden.skaldr-state.json"
    save_state(path, _state().model_copy(update={"doc_id": OTHER_DOC_ID}))
    expected = (
        f"{path} records the publishing of 'kitchen-rota', not 'garden-handbook'; each document keeps its "
        "own state file next to it, so rename one of the two documents' files or restore the right state file"
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
        f"{path} is not a publish state skaldr can read; restore it from version control or a backup, since "
        "without it skaldr no longer knows which pages and issues it created"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        load_state(path, DOC_ID)
