import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from skaldr.auth.templates import clear_notion_template, save_notion_template
from skaldr.publish import ConnectorRegistry
from skaldr.publish.cli import main
from skaldr.publish.notion.connector import NotionConnector
from skaldr.publish.state import state_path_for
from tests.factories import NOTION_PAGE_ID, NOTION_PAGE_URL
from tests.factories.auth_factory import (
    OTHER_WORKSPACE_ID,
    WORKSPACE_ID,
    make_notion_credentials,
    seed_notion,
)
from tests.factories.notion_factory import InMemoryNotion, Scripted, numbered_id
from tests.factories.publish_factory import make_notion_publish, write_garden_report

TEMPLATE_PAGE = "aabbccddeeff00112233445566778899"
OTHER_TEMPLATE_PAGE = "00112233445566778899aabbccddeeff"
TEMPLATE = {"type": "template_id", "template_id": TEMPLATE_PAGE}
OTHER_TEMPLATE = {"type": "template_id", "template_id": OTHER_TEMPLATE_PAGE}
WORKSPACE = UUID(WORKSPACE_ID)
OTHER_WORKSPACE = UUID(OTHER_WORKSPACE_ID)
DOCUMENT_PAGE = numbered_id(1).replace("-", "")
TOOLS_PAGE = numbered_id(2).replace("-", "")


def _notion() -> InMemoryNotion:
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Team plans")
    notion.add_page(TEMPLATE_PAGE, "Page template", "")
    notion.add_page(OTHER_TEMPLATE_PAGE, "Another template", "")
    return notion


def _registry(notion: InMemoryNotion) -> ConnectorRegistry:
    return ConnectorRegistry([NotionConnector(http=notion.mock(), sleep=lambda _: None)])


def _publish(notion: InMemoryNotion, directory: Path, **overrides: Any) -> int:
    directory.mkdir(exist_ok=True)
    path = write_garden_report(directory, **overrides)
    return main(["publish", str(path), "--apply"], registry=_registry(notion))


def _create_bodies(notion: InMemoryNotion) -> list[dict[str, Any]]:
    return [
        json.loads(request.content)
        for request in notion.requests
        if (request.method, request.url.path) == ("POST", "/v1/pages")
    ]


def _templates_of_the_creates(notion: InMemoryNotion) -> list[Any]:
    return [body.get("template") for body in _create_bodies(notion)]


def _reads_of(notion: InMemoryNotion, page_id: str) -> int:
    return sum(
        1
        for request in notion.requests
        if request.method == "GET" and request.url.path == f"/v1/pages/{page_id}/markdown"
    )


def _target_with(**where: Any) -> dict[str, Any]:
    return make_notion_publish(split=["tools"], where={"parent_page": NOTION_PAGE_URL, **where})


def test_every_page_of_a_publish_is_created_from_the_workspace_template_and_ends_as_it_would_without_one(
    tmp_path: Path,
) -> None:
    seed_notion(make_notion_credentials())
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    templated = _notion()
    plain = _notion()

    first = _publish(templated, tmp_path / "templated")
    clear_notion_template(WORKSPACE)
    second = _publish(plain, tmp_path / "plain")

    assert (first, second) == (0, 0)
    assert (
        _templates_of_the_creates(templated),
        _reads_of(templated, TEMPLATE_PAGE),
        templated.markdown_of(DOCUMENT_PAGE),
        templated.markdown_of(TOOLS_PAGE),
    ) == (
        [TEMPLATE, TEMPLATE],
        1,
        plain.markdown_of(DOCUMENT_PAGE),
        plain.markdown_of(TOOLS_PAGE),
    )


def test_a_workspace_without_a_template_publishes_with_the_markdown_in_the_create_and_saves_no_template_key(
    tmp_path: Path,
) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion()

    exit_code = _publish(notion, tmp_path)

    assert (
        exit_code,
        [sorted(body) for body in _create_bodies(notion)],
        [body["allow_async"] for body in _create_bodies(notion)],
        "template" in state_path_for(tmp_path / "doc.yaml").read_text(encoding="utf-8"),
    ) == (
        0,
        [["allow_async", "markdown", "parent", "properties"]] * 2,
        [True, True],
        False,
    )


def test_a_template_cleared_between_runs_is_not_used_by_the_next_run(tmp_path: Path) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion()
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    _publish(notion, tmp_path / "first")
    clear_notion_template(WORKSPACE)

    _publish(notion, tmp_path / "second")

    assert [body.get("template") for body in _create_bodies(notion)] == [TEMPLATE, TEMPLATE, None, None]


def test_a_template_changed_between_runs_is_the_one_the_next_run_creates_from(tmp_path: Path) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion()
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    _publish(notion, tmp_path / "first")
    save_notion_template(WORKSPACE, OTHER_TEMPLATE_PAGE)

    _publish(notion, tmp_path / "second")

    assert _templates_of_the_creates(notion) == [TEMPLATE, TEMPLATE, OTHER_TEMPLATE, OTHER_TEMPLATE]


def test_a_template_set_after_a_run_is_picked_up_by_the_next_run_without_touching_the_first_page(
    tmp_path: Path,
) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion()
    _publish(notion, tmp_path / "first")
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)

    _publish(notion, tmp_path / "second")

    assert _templates_of_the_creates(notion) == [None, None, TEMPLATE, TEMPLATE]


def test_a_template_in_the_target_wins_over_the_workspace_template(tmp_path: Path) -> None:
    seed_notion(make_notion_credentials())
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    notion = _notion()

    _publish(notion, tmp_path, publish=_target_with(template=OTHER_TEMPLATE_PAGE))

    assert (_templates_of_the_creates(notion), _reads_of(notion, TEMPLATE_PAGE)) == (
        [OTHER_TEMPLATE, OTHER_TEMPLATE],
        0,
    )


def test_a_target_that_names_none_creates_without_the_workspace_template(tmp_path: Path) -> None:
    seed_notion(make_notion_credentials())
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    notion = _notion()

    exit_code = _publish(notion, tmp_path, publish=_target_with(template="none"))

    assert (exit_code, _templates_of_the_creates(notion), _reads_of(notion, TEMPLATE_PAGE)) == (
        0,
        [None, None],
        0,
    )


def test_a_workspace_template_that_is_not_empty_stops_the_publish_before_anything_is_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_notion(make_notion_credentials())
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    notion = _notion()
    notion.pages[TEMPLATE_PAGE].markdown = "## Boilerplate"

    exit_code = _publish(notion, tmp_path)

    assert (exit_code, notion.writes(), capsys.readouterr().err) == (
        1,
        [],
        f"error: the Notion template page {TEMPLATE_PAGE} is not empty, so Notion would copy its content "
        "into every page skaldr creates from it; empty the page in Notion, or choose another template page\n",
    )


@pytest.mark.parametrize(
    ("workspace", "templates"),
    [
        pytest.param(WORKSPACE_ID, [None, None], id="the-workspace-without-a-template"),
        pytest.param(OTHER_WORKSPACE_ID, [TEMPLATE, TEMPLATE], id="the-workspace-with-one"),
    ],
)
def test_the_template_is_the_one_of_the_workspace_the_target_signs_in_with(
    tmp_path: Path, workspace: str, templates: list[Any]
) -> None:
    seed_notion(make_notion_credentials())
    seed_notion(make_notion_credentials(workspace_id=OTHER_WORKSPACE_ID, workspace_name="Other Workspace"))
    save_notion_template(OTHER_WORKSPACE, TEMPLATE_PAGE)
    notion = _notion()

    exit_code = _publish(notion, tmp_path, publish=_target_with(workspace=workspace))

    assert (exit_code, _templates_of_the_creates(notion)) == (0, templates)


def test_a_sign_in_from_the_environment_has_no_workspace_so_no_workspace_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOTION_ACCESS_TOKEN", "access-token")
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    notion = _notion()

    exit_code = _publish(notion, tmp_path)

    assert (exit_code, _templates_of_the_creates(notion)) == (0, [None, None])


def test_a_sign_in_from_the_environment_still_creates_from_a_template_the_target_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOTION_ACCESS_TOKEN", "access-token")
    notion = _notion()

    exit_code = _publish(notion, tmp_path, publish=_target_with(template=TEMPLATE_PAGE))

    assert (exit_code, _templates_of_the_creates(notion)) == (0, [TEMPLATE, TEMPLATE])


def test_a_page_left_empty_by_a_fill_that_failed_is_adopted_and_filled_by_the_next_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_notion(make_notion_credentials())
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    notion = _notion()
    notion.scripted = [
        Scripted(500, {"object": "error"}, method="PATCH", path=f"/v1/pages/{DOCUMENT_PAGE}/markdown")
    ]
    path = write_garden_report(tmp_path)

    interrupted = main(["publish", str(path), "--apply"], registry=_registry(notion))
    left_behind = notion.markdown_of(DOCUMENT_PAGE)
    capsys.readouterr()
    reruns = [main(["publish", str(path), "--apply"], registry=_registry(notion)) for _ in range(2)]

    plain = _notion()
    main(["publish", str(write_garden_report(tmp_path / "plain")), "--apply"], registry=_registry(plain))
    assert (interrupted, left_behind, reruns[-1]) == (1, "", 0)
    assert sorted(notion.markdown_of(DOCUMENT_PAGE).splitlines()) == sorted(
        plain.markdown_of(DOCUMENT_PAGE).splitlines()
    )
    assert notion.markdown_of(TOOLS_PAGE) == plain.markdown_of(TOOLS_PAGE)


def test_a_run_that_creates_nothing_never_reads_the_template_and_leaves_existing_pages_alone(
    tmp_path: Path,
) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    notion.requests.clear()

    again = main(["publish", str(path), "--apply"], registry=_registry(notion))

    assert (again, notion.writes(), [r.url.path for r in notion.requests if TEMPLATE_PAGE in r.url.path]) == (
        0,
        [],
        [],
    )


def test_a_page_a_person_deleted_is_created_again_from_the_template_set_by_then(tmp_path: Path) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    notion.pages[TOOLS_PAGE].in_trash = True
    save_notion_template(WORKSPACE, OTHER_TEMPLATE_PAGE)
    notion.requests.clear()

    exit_code = main(["publish", str(path), "--apply", "--overwrite"], registry=_registry(notion))

    assert (exit_code, _templates_of_the_creates(notion)) == (0, [OTHER_TEMPLATE])


def test_a_template_with_a_database_parent_stops_the_publish_before_anything_is_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_notion(make_notion_credentials())
    notion = InMemoryNotion()
    notion.add_database(NOTION_PAGE_ID)
    notion.add_page(TEMPLATE_PAGE, "Page template", "")

    exit_code = _publish(notion, tmp_path, publish=_target_with(template=TEMPLATE_PAGE))

    assert (exit_code, notion.writes(), capsys.readouterr().err) == (
        1,
        [],
        f"error: Notion database {NOTION_PAGE_ID} does not take a page template, so skaldr cannot create its "
        "rows from one; remove `template` from the target's `where`, or set it to `none`\n",
    )
