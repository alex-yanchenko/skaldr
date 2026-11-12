from pathlib import Path

import pytest

from skaldr.publish.cli import main
from skaldr.publish.engine import Applied, apply_publish, dry_run_publish, prepare_publish
from skaldr.publish.plan import describe_plan
from tests.factories import NOTION_PAGE_ID
from tests.factories.auth_factory import make_notion_credentials, seed_notion
from tests.factories.notion_factory import InMemoryNotion, notion_registry
from tests.factories.publish_factory import (
    DOC_ID,
    INTO_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_meta,
    make_notion_publish,
    write_garden_report,
)

INTO_THE_PAGE = make_notion_publish(where={"page": NOTION_PAGE_ID})
ADOPTION = f"adopt    document into {NOTION_PAGE_ID} (replaces content stamped with doc_id '{DOC_ID}')"


def test_a_page_stamped_with_this_doc_id_that_the_state_file_does_not_record_is_planned_as_an_adoption(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Kitchen rota", DOC_ID, {"intro": "Another copy wrote this.\n"})
    path = write_garden_report(tmp_path, publish=INTO_THE_PAGE)

    dry_run = dry_run_publish(prepare_publish(path, fake_registry(transport)))
    written_by_the_dry_run = transport.writes()
    outcome = apply_publish(prepare_publish(path, fake_registry(transport)))

    assert (describe_plan(dry_run.plan), written_by_the_dry_run, outcome) == (
        [f"{INTO_LABEL}: 1 to create, 0 to update, 0 to archive", f"  {ADOPTION}"],
        [],
        Applied((ADOPTION,)),
    )


def test_an_empty_page_stamped_with_this_doc_id_is_planned_as_a_plain_write_into_it(tmp_path: Path) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", DOC_ID)
    path = write_garden_report(tmp_path, publish=INTO_THE_PAGE)

    dry_run = dry_run_publish(prepare_publish(path, fake_registry(transport)))

    assert describe_plan(dry_run.plan) == [
        f"{INTO_LABEL}: 1 to create, 0 to update, 0 to archive",
        f'  create   document "Garden handbook" into {NOTION_PAGE_ID}',
    ]


def test_a_second_document_with_the_same_doc_id_says_it_replaces_the_page_the_first_one_wrote(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_notion(make_notion_credentials())
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Team plans")
    registry = notion_registry(notion)
    main(["publish", str(write_garden_report(tmp_path, publish=INTO_THE_PAGE)), "--apply"], registry=registry)
    (tmp_path / "copy").mkdir()
    copy = write_garden_report(
        tmp_path / "copy", publish=INTO_THE_PAGE, meta=make_garden_meta(title="Kitchen rota")
    )
    notion.requests.clear()
    capsys.readouterr()

    exit_code = main(["publish", str(copy)], registry=registry)

    assert (exit_code, capsys.readouterr().out, notion.writes()) == (
        0,
        f"{INTO_LABEL}: 1 to create, 0 to update, 0 to archive\n"
        f"  {ADOPTION}\n"
        f"Dry run: nothing was sent. Publish with `skaldr publish {copy} --apply`.\n",
        [],
    )
