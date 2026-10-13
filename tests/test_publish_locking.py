import re
from pathlib import Path

import pytest

from skaldr.errors import PublishError
from skaldr.publish.engine import Applied, apply_publish, diff_publish, dry_run_publish, prepare_publish
from skaldr.publish.state import LOCK_FILE_SUFFIX, state_path_for
from skaldr.publish_block import JiraTarget, NotionTarget
from tests.factories.publish_factory import (
    DOC_ID,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
    make_notion_publish,
    write_garden_report,
)
from tests.factories.report_factory import NOTION_PAGE_ID, make_jira_target


def _lock_path(document: Path) -> Path:
    return Path(str(state_path_for(document)) + LOCK_FILE_SUFFIX)


def test_an_apply_prepared_before_another_apply_plans_again_from_the_state_it_finds(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    stale = prepare_publish(path, fake_registry(transport))
    apply_publish(prepare_publish(path, fake_registry(transport)))
    transport.forget_calls()

    outcome = apply_publish(stale)

    assert (outcome, transport.writes(), sorted(transport.items)) == (Applied(()), [], ["page-1", "page-2"])


def test_a_diff_prepared_before_an_apply_reads_the_state_it_finds(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    stale = prepare_publish(path, fake_registry(transport))
    apply_publish(prepare_publish(path, fake_registry(transport)))

    diff = diff_publish(stale)

    assert (diff.remote_edits, diff.yaml_changes, diff.missing_remotely) == ((), (), ())


def test_a_dry_run_of_a_new_document_leaves_no_state_file_and_no_lock_file(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)

    dry_run_publish(prepare_publish(path, fake_registry(transport)))

    assert (transport.writes(), state_path_for(path).exists(), _lock_path(path).exists()) == (
        [],
        False,
        False,
    )


def test_a_dry_run_after_a_publish_leaves_the_state_file_as_it_was(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path)
    apply_publish(prepare_publish(path, fake_registry(transport)))
    write_garden_report(tmp_path, blocks=make_garden_blocks(tools="Rake.", planting="Sow in May."))
    before = state_path_for(path).read_bytes()
    transport.forget_calls()

    dry_run_publish(prepare_publish(path, fake_registry(transport)))

    assert (transport.writes(), state_path_for(path).read_bytes()) == ([], before)


def test_an_apply_in_a_folder_skaldr_cannot_write_to_is_refused_before_any_call(tmp_path: Path) -> None:
    transport = FakeTransport()
    folder = tmp_path / "plans"
    path = write_garden_report(folder)
    prepared = prepare_publish(path, fake_registry(transport))
    folder.chmod(0o555)
    expected = (
        f"skaldr keeps the publish state next to the document, and {folder} is not writable; make it "
        "writable, or move the document somewhere it is"
    )

    try:
        with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
            apply_publish(prepared)
    finally:
        folder.chmod(0o755)
    assert transport.calls == []


def test_a_released_page_that_is_already_gone_is_forgotten_without_a_call(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    registry = fake_registry(transport, target_types=(NotionTarget, JiraTarget))
    path = write_garden_report(tmp_path, publish=make_notion_publish(where={"page": NOTION_PAGE_ID}))
    apply_publish(prepare_publish(path, registry))
    write_garden_report(tmp_path, publish={"doc_id": DOC_ID, "targets": [make_jira_target()]})
    transport.delete_item_by_hand(NOTION_PAGE_ID)
    transport.forget_calls()

    apply_publish(prepare_publish(path, registry), overwrite=True)

    assert [call for call in transport.writes() if call[0] != "create"] == []
