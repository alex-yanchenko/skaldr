import json
import re
from pathlib import Path
from typing import Any

import pytest

from skaldr.auth.store import SignIn, load_notion
from skaldr.errors import AuthError, ConnectorError, PublishError
from skaldr.export.budget import json_string_bytes
from skaldr.export.notion import notion_block_count
from skaldr.publish import ConnectorRegistry, ContentLimit
from skaldr.publish.cli import installed_connectors, main
from skaldr.publish.content import ItemContent
from skaldr.publish.drafts import authored_from, draft_targets
from skaldr.publish.notion.connector import NotionConnector
from skaldr.publish_block import JiraTarget, NotionTarget
from tests.factories import NOTION_PAGE_ID, make_jira_target, make_notion_target, make_report
from tests.factories.auth_factory import (
    OTHER_WORKSPACE_ID,
    WORKSPACE_ID,
    basic_auth_header,
    make_notion_credentials,
    seed_notion,
)
from tests.factories.notion_factory import PERSON_ID, InMemoryNotion, Scripted, numbered_id
from tests.factories.publish_factory import (
    DOC_ID,
    TARGET_LABEL,
    make_garden_blocks,
    make_garden_meta,
    make_notion_publish,
    write_garden_report,
)

DOCUMENT_PAGE = numbered_id(1).replace("-", "")
TOOLS_PAGE = numbered_id(2).replace("-", "")
SEEDLING = "🌱"
SUNFLOWER = "🌻"
COVER_URL = "https://example.com/garden.png"
SEEDLING_ICON = {"type": "emoji", "emoji": SEEDLING}
SUNFLOWER_ICON = {"type": "emoji", "emoji": SUNFLOWER}
GARDEN_COVER = {"type": "external", "external": {"url": COVER_URL}}


def _connector(notion: InMemoryNotion) -> NotionConnector:
    return NotionConnector(http=notion.mock(), sleep=lambda _: None)


def _registry(notion: InMemoryNotion) -> ConnectorRegistry:
    return ConnectorRegistry([_connector(notion)])


def _notion_with_a_parent_page() -> InMemoryNotion:
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Team plans")
    return notion


def _markdown_writes(notion: InMemoryNotion) -> list[Any]:
    return [
        json.loads(request.content)
        for request in notion.requests
        if request.method == "PATCH" and request.url.path.endswith("/markdown")
    ]


def test_skaldr_has_a_notion_connector_installed_and_none_for_jira() -> None:
    registry = installed_connectors()

    assert isinstance(registry.for_target(NotionTarget.model_validate(make_notion_target())), NotionConnector)
    with pytest.raises(ConnectorError, match=r"^no connector publishes to jira$"):
        registry.for_target(JiraTarget.model_validate(make_jira_target()))


def test_the_notion_connector_writes_sections_within_one_creates_budget_and_carries_the_look() -> None:
    connector = NotionConnector()

    assert (connector.target_type, connector.writes, connector.limits, connector.carries_look) == (
        NotionTarget,
        "section",
        (
            ContentLimit("section", 4_999, "Notion blocks", notion_block_count),
            ContentLimit("section", 200_000, "bytes of JSON", json_string_bytes),
        ),
        True,
    )


def _report_with_a_tools_section(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return make_report(
        meta={"title": "Garden handbook"},
        publish=make_notion_publish(),
        blocks=[{"type": "section", "id": "tools", "title": "Tools", "collapsed": False, "blocks": blocks}],
    )


@pytest.mark.parametrize(
    ("blocks", "measured"),
    [
        pytest.param(
            [{"type": "list", "items": [f"Tool {number}." for number in range(5_000)]}],
            "5,001 Notion blocks, over the 4,999",
            id="blocks",
        ),
        pytest.param(
            [{"type": "text", "body": "a" * 200_000}], "200,012 bytes of JSON, over the 200,000", id="bytes"
        ),
    ],
)
def test_a_section_over_what_one_notion_request_takes_stops_the_plan_and_points_at_split(
    blocks: list[dict[str, Any]], measured: str
) -> None:
    expected = (
        f"{TARGET_LABEL}, document: section tools (blocks[0]) has {measured} a Notion section can take; "
        "split the document further with `split`, or shorten it"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        draft_targets(authored_from(_report_with_a_tools_section(blocks)), installed_connectors())


def test_a_page_target_names_the_page_it_writes_into_and_a_parent_page_target_names_none() -> None:
    connector = NotionConnector()
    into = NotionTarget.model_validate(
        make_notion_target(where={"page": f"https://www.notion.so/Plan-{NOTION_PAGE_ID}"})
    )

    assert (
        connector.existing_item_id(into),
        connector.existing_item_id(NotionTarget.model_validate(make_notion_target())),
    ) == (NOTION_PAGE_ID, None)


def test_a_transport_signs_in_at_its_first_request_and_says_to_sign_in_when_nothing_is_stored() -> None:
    notion = _notion_with_a_parent_page()
    transport = _connector(notion).open_transport(NotionTarget.model_validate(make_notion_target()))

    with pytest.raises(AuthError, match=r"^Not signed in to Notion; run `skaldr auth notion`$"):
        transport.read_item(NOTION_PAGE_ID, ItemContent(title=""))
    assert notion.requests == []


def test_applying_without_a_notion_sign_in_stops_before_anything_is_sent_and_leaves_no_pending_create(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion_with_a_parent_page()
    path = write_garden_report(tmp_path)

    first = main(["publish", str(path), "--apply"], registry=_registry(notion))
    again = main(["publish", str(path), "--apply"], registry=_registry(notion))

    assert (first, again, capsys.readouterr().err, notion.requests) == (
        1,
        1,
        "error: Not signed in to Notion; run `skaldr auth notion`\n" * 2,
        [],
    )


def test_a_refused_stored_token_is_renewed_saved_to_the_keychain_and_the_read_sent_again() -> None:
    seed_notion(make_notion_credentials(access_token="lapsed-access"))
    notion = _notion_with_a_parent_page()
    transport = _connector(notion).open_transport(NotionTarget.model_validate(make_notion_target()))

    read = transport.read_item(NOTION_PAGE_ID, ItemContent(title=""))

    sent = [(request.url.path, request.headers.get("authorization")) for request in notion.requests]
    assert (read.comparable.title, sent, load_notion()) == (
        "Team plans",
        [
            (f"/v1/pages/{NOTION_PAGE_ID}", "Bearer lapsed-access"),
            ("/v1/oauth/token", basic_auth_header("client-id", "client-secret")),
            (f"/v1/pages/{NOTION_PAGE_ID}", "Bearer renewed-access"),
            (f"/v1/pages/{NOTION_PAGE_ID}/markdown", "Bearer renewed-access"),
        ],
        SignIn(
            make_notion_credentials(access_token="renewed-access", refresh_token="renewed-refresh"),
            "keychain",
        ),
    )


def _notion_target_in(workspace: str | None) -> NotionTarget:
    where: dict[str, Any] = {"parent_page": NOTION_PAGE_ID}
    if workspace is not None:
        where["workspace"] = workspace
    return NotionTarget.model_validate(make_notion_target(where=where))


def _read_the_parent_page(workspace: str | None, notion: InMemoryNotion) -> str:
    transport = _connector(notion).open_transport(_notion_target_in(workspace))
    return transport.read_item(NOTION_PAGE_ID, ItemContent(title="")).comparable.title


def _sign_in_to_two_workspaces() -> None:
    seed_notion(make_notion_credentials(access_token="lapsed-access"))
    seed_notion(make_notion_credentials(workspace_id=OTHER_WORKSPACE_ID, workspace_name="Other Workspace"))


def test_a_transport_opened_for_a_target_of_another_service_signs_in_without_a_workspace() -> None:
    _sign_in_to_two_workspaces()
    notion = _notion_with_a_parent_page()
    transport = _connector(notion).open_transport(JiraTarget.model_validate(make_jira_target()))

    with pytest.raises(AuthError) as caught:
        transport.read_item(NOTION_PAGE_ID, ItemContent(title=""))

    assert (str(caught.value), notion.requests) == (
        f"Signed in to several Notion workspaces (Example Workspace ({WORKSPACE_ID}), "
        f"Other Workspace ({OTHER_WORKSPACE_ID})); name one with `workspace` in the target's `where`",
        [],
    )


def test_a_target_without_a_workspace_uses_the_only_sign_in() -> None:
    seed_notion(make_notion_credentials(access_token="access-token"))
    notion = _notion_with_a_parent_page()

    assert _read_the_parent_page(None, notion) == "Team plans"


def test_a_target_without_a_workspace_names_the_key_to_set_when_signed_in_to_several() -> None:
    _sign_in_to_two_workspaces()
    notion = _notion_with_a_parent_page()

    with pytest.raises(
        AuthError,
        match=re.escape(
            f"Signed in to several Notion workspaces (Example Workspace ({WORKSPACE_ID}), "
            f"Other Workspace ({OTHER_WORKSPACE_ID})); name one with `workspace` in the target's `where`"
        ),
    ):
        _read_the_parent_page(None, notion)
    assert notion.requests == []


def test_a_target_naming_a_workspace_two_sign_ins_share_is_told_to_name_one_by_its_id() -> None:
    seed_notion(make_notion_credentials())
    seed_notion(make_notion_credentials(workspace_id=OTHER_WORKSPACE_ID))
    notion = _notion_with_a_parent_page()

    with pytest.raises(AuthError) as caught:
        _read_the_parent_page("Example Workspace", notion)

    assert (str(caught.value), notion.requests) == (
        f"Signed in to several Notion workspaces named `Example Workspace` (Example Workspace "
        f"({WORKSPACE_ID}), Example Workspace ({OTHER_WORKSPACE_ID})); name one by its id with `workspace` "
        "in the target's `where`",
        [],
    )


@pytest.mark.parametrize("workspace", [WORKSPACE_ID, "Example Workspace"])
def test_a_target_names_its_workspace_by_id_or_by_name_and_the_renewal_is_saved_to_that_entry(
    workspace: str,
) -> None:
    _sign_in_to_two_workspaces()
    notion = _notion_with_a_parent_page()

    title = _read_the_parent_page(workspace, notion)

    assert (title, load_notion(WORKSPACE_ID), load_notion(OTHER_WORKSPACE_ID)) == (
        "Team plans",
        SignIn(
            make_notion_credentials(access_token="renewed-access", refresh_token="renewed-refresh"),
            "keychain",
        ),
        SignIn(
            make_notion_credentials(workspace_id=OTHER_WORKSPACE_ID, workspace_name="Other Workspace"),
            "keychain",
        ),
    )


def test_a_workspace_that_matches_no_sign_in_lists_the_signed_in_workspaces() -> None:
    _sign_in_to_two_workspaces()
    notion = _notion_with_a_parent_page()

    with pytest.raises(
        AuthError,
        match=re.escape(
            "No Notion sign-in matches workspace `Missing Workspace`; signed in to Example Workspace "
            f"({WORKSPACE_ID}), Other Workspace ({OTHER_WORKSPACE_ID})"
        ),
    ):
        _read_the_parent_page("Missing Workspace", notion)
    assert notion.requests == []


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(["publish", "--apply"], id="apply"),
        pytest.param(["publish"], id="dry-run"),
        pytest.param(["diff"], id="diff"),
        pytest.param(["status"], id="status"),
    ],
)
def test_every_command_closes_the_notion_client_it_opened(tmp_path: Path, command: list[str]) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion_with_a_parent_page()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    closed_before = notion.closes

    exit_code = main([command[0], str(path), *command[1:]], registry=_registry(notion))

    assert (exit_code, notion.closes - closed_before) == (0, 1)


def test_a_release_stopped_before_it_cleared_the_icon_is_sent_again_on_the_next_run(tmp_path: Path) -> None:
    seed_notion(make_notion_credentials())
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Blank page")
    into_the_page = make_notion_publish(where={"page": NOTION_PAGE_ID})
    path = write_garden_report(tmp_path, meta=make_garden_meta(icon=SEEDLING), publish=into_the_page)
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    retired: dict[str, Any] = {"doc_id": DOC_ID, "targets": []}
    write_garden_report(tmp_path, meta=make_garden_meta(icon=SEEDLING), publish=retired)
    notion.scripted.append(
        Scripted(500, {"object": "error"}, method="PATCH", path=f"/v1/pages/{NOTION_PAGE_ID}")
    )

    interrupted = main(["publish", str(path), "--apply"], registry=_registry(notion))
    icon_after_the_interruption = notion.pages[NOTION_PAGE_ID].icon
    again = main(["publish", str(path), "--apply"], registry=_registry(notion))

    assert (interrupted, icon_after_the_interruption, again, notion.pages[NOTION_PAGE_ID].icon) == (
        1,
        SEEDLING_ICON,
        0,
        None,
    )


def test_a_dry_run_that_renews_the_sign_in_saves_it_so_a_rotated_refresh_token_is_never_lost(
    tmp_path: Path,
) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion_with_a_parent_page()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    notion.accepted_token = "issued-elsewhere"

    exit_code = main(["publish", str(path)], registry=_registry(notion))

    assert (exit_code, load_notion()) == (
        0,
        SignIn(
            make_notion_credentials(access_token="renewed-access", refresh_token="renewed-refresh"),
            "keychain",
        ),
    )


def test_publishing_creates_the_document_and_its_split_page_and_publishing_again_sends_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion_with_a_parent_page()
    path = write_garden_report(tmp_path)

    first = main(["publish", str(path), "--apply"], registry=_registry(notion))
    created = notion.writes()
    again = main(["publish", str(path), "--apply"], registry=_registry(notion))

    assert (first, again, created, notion.writes()[len(created) :]) == (
        0,
        0,
        [("POST", "/v1/pages"), ("POST", "/v1/pages")],
        [],
    )
    assert capsys.readouterr().out.splitlines()[-1] == "Nothing to publish: every item matches the YAML."
    assert (
        notion.markdown_of(DOCUMENT_PAGE).splitlines()[-2:],
        notion.markdown_of(TOOLS_PAGE).splitlines()[-1],
    ) == (
        [
            'Published with skaldr from document garden-handbook {color="gray"}',
            f'<page url="https://www.notion.so/{TOOLS_PAGE}">Tools</page>',
        ],
        'Published with skaldr from document garden-handbook, section tools {color="gray"}',
    )


def test_a_section_change_puts_back_the_stamp_a_person_deleted(tmp_path: Path) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion_with_a_parent_page()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    stamp = 'Published with skaldr from document garden-handbook, section tools {color="gray"}'
    notion.edit_by_hand(TOOLS_PAGE, f"\n{stamp}", "")
    write_garden_report(tmp_path, blocks=make_garden_blocks(tools="Rake."))

    exit_code = main(["publish", str(path), "--apply"], registry=_registry(notion))

    assert (exit_code, notion.markdown_of(TOOLS_PAGE).splitlines()[-2:]) == (0, ["- Rake.", stamp])


def _edited_by_lines_of_a_diff_after_two_hand_edits(
    tmp_path: Path, notion: InMemoryNotion, capsys: pytest.CaptureFixture[str]
) -> tuple[list[str], list[str]]:
    seed_notion(make_notion_credentials())
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    notion.edit_by_hand(DOCUMENT_PAGE, "Sow in spring.", "Sow in June.")
    notion.edit_by_hand(TOOLS_PAGE, "- Spade.", "- Trowel.")
    capsys.readouterr()
    notion.requests.clear()

    main(["diff", str(path)], registry=_registry(notion))

    edited = [line for line in capsys.readouterr().out.splitlines() if "edited by" in line]
    asked = [request.url.path for request in notion.requests if request.url.path.startswith("/v1/users/")]
    return edited, asked


def test_a_remote_edit_names_the_person_notion_says_made_it_and_asks_once_per_person(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion_with_a_parent_page()
    notion.users[PERSON_ID] = "Rowan Ash"

    edited, asked = _edited_by_lines_of_a_diff_after_two_hand_edits(tmp_path, notion, capsys)

    assert (edited, asked) == (
        [
            f"+++ {TARGET_LABEL}, document: planting (blocks[2]), now, edited by Rowan Ash at "
            "2026-10-09T12:06:00+00:00",
            f"+++ {TARGET_LABEL}, section tools: tools (blocks[1]), now, edited by Rowan Ash at "
            "2026-10-09T12:07:00+00:00",
        ],
        [f"/v1/users/{PERSON_ID}"],
    )


def test_a_remote_edit_by_a_person_notion_will_not_name_shows_their_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion_with_a_parent_page()

    edited, asked = _edited_by_lines_of_a_diff_after_two_hand_edits(tmp_path, notion, capsys)

    assert (edited, asked) == (
        [
            f"+++ {TARGET_LABEL}, document: planting (blocks[2]), now, edited by {PERSON_ID} at "
            "2026-10-09T12:06:00+00:00",
            f"+++ {TARGET_LABEL}, section tools: tools (blocks[1]), now, edited by {PERSON_ID} at "
            "2026-10-09T12:07:00+00:00",
        ],
        [f"/v1/users/{PERSON_ID}"],
    )


def test_a_changed_section_is_sent_as_one_search_and_replace(tmp_path: Path) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion_with_a_parent_page()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    write_garden_report(tmp_path, blocks=make_garden_blocks(planting="Sow in late spring."))
    notion.requests.clear()

    exit_code = main(["publish", str(path), "--apply"], registry=_registry(notion))

    assert (exit_code, _markdown_writes(notion)) == (
        0,
        [
            {
                "type": "update_content",
                "update_content": {
                    "content_updates": [
                        {
                            "old_str": "## Planting\nSow in spring.\n",
                            "new_str": "## Planting\nSow in late spring.\n",
                        }
                    ]
                },
                "allow_async": True,
            }
        ],
    )


def test_an_edit_made_in_notion_stops_the_publish_until_it_is_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion_with_a_parent_page()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    notion.edit_by_hand(DOCUMENT_PAGE, "Sow in spring.", "Sow in June.")
    capsys.readouterr()

    refused = main(["publish", str(path), "--apply"], registry=_registry(notion))
    refusal = capsys.readouterr()
    overwritten = main(["publish", str(path), "--apply", "--overwrite"], registry=_registry(notion))

    assert (refused, refusal.err, overwritten, "Sow in spring." in notion.markdown_of(DOCUMENT_PAGE)) == (
        1,
        "error: 1 part was edited in the service since the last publish, so nothing was written. To keep the "
        "edit, copy it into the YAML first; to replace it, publish with --apply --overwrite.\n",
        0,
        True,
    )
    assert "-Sow in spring.\n+Sow in June." in refusal.out


def _page_writes(notion: InMemoryNotion) -> list[tuple[str, Any]]:
    return [
        (request.url.path, json.loads(request.content))
        for request in notion.requests
        if request.method == "PATCH" and not request.url.path.endswith("/markdown")
    ]


def test_publishing_sets_the_icon_and_cover_then_changes_and_clears_them_as_the_yaml_does(
    tmp_path: Path,
) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion_with_a_parent_page()
    path = write_garden_report(tmp_path, meta=make_garden_meta(icon=SEEDLING, cover=COVER_URL))
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    published = [(notion.pages[page].icon, notion.pages[page].cover) for page in (DOCUMENT_PAGE, TOOLS_PAGE)]
    write_garden_report(tmp_path, meta=make_garden_meta(icon=SUNFLOWER))
    notion.requests.clear()

    changed = main(["publish", str(path), "--apply"], registry=_registry(notion))
    changes = _page_writes(notion)
    notion.requests.clear()
    again = main(["publish", str(path), "--apply"], registry=_registry(notion))

    assert (published, changed, changes, again, notion.writes()) == (
        [(SEEDLING_ICON, GARDEN_COVER), (SEEDLING_ICON, None)],
        0,
        [
            (f"/v1/pages/{DOCUMENT_PAGE}", {"icon": SUNFLOWER_ICON, "cover": None}),
            (f"/v1/pages/{TOOLS_PAGE}", {"icon": SUNFLOWER_ICON}),
        ],
        0,
        [],
    )


def test_an_icon_changed_in_notion_stops_the_publish_until_it_is_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion_with_a_parent_page()
    path = write_garden_report(tmp_path, meta=make_garden_meta(icon=SEEDLING))
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    notion.set_look_by_hand(DOCUMENT_PAGE, icon={"type": "emoji", "emoji": "🔥"}, cover=None)
    capsys.readouterr()

    refused = main(["publish", str(path), "--apply"], registry=_registry(notion))
    refusal = capsys.readouterr()
    overwritten = main(["publish", str(path), "--apply", "--overwrite"], registry=_registry(notion))

    assert (refused, overwritten, notion.pages[DOCUMENT_PAGE].icon) == (1, 0, SEEDLING_ICON)
    assert f"-{SEEDLING}\n+🔥" in refusal.out


def test_an_icon_and_cover_a_person_adds_in_notion_to_a_page_without_them_are_kept(tmp_path: Path) -> None:
    seed_notion(make_notion_credentials())
    notion = _notion_with_a_parent_page()
    path = write_garden_report(tmp_path)
    main(["publish", str(path), "--apply"], registry=_registry(notion))
    notion.set_look_by_hand(DOCUMENT_PAGE, icon={"type": "emoji", "emoji": "🔥"}, cover=GARDEN_COVER)
    notion.requests.clear()

    exit_code = main(["publish", str(path), "--apply"], registry=_registry(notion))

    assert (
        exit_code,
        notion.writes(),
        notion.pages[DOCUMENT_PAGE].icon,
        notion.pages[DOCUMENT_PAGE].cover,
    ) == (
        0,
        [],
        {"type": "emoji", "emoji": "🔥"},
        GARDEN_COVER,
    )
