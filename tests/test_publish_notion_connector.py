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
from tests.factories.auth_factory import basic_auth_header, make_notion_credentials, seed_notion
from tests.factories.notion_factory import InMemoryNotion, numbered_id
from tests.factories.publish_factory import (
    TARGET_LABEL,
    make_garden_blocks,
    make_notion_publish,
    write_garden_report,
)

DOCUMENT_PAGE = numbered_id(1).replace("-", "")
TOOLS_PAGE = numbered_id(2).replace("-", "")


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


def test_the_notion_connector_writes_one_section_at_a_time_within_one_creates_budget() -> None:
    connector = NotionConnector()

    assert (connector.target_type, connector.writes, connector.limits) == (
        NotionTarget,
        "section",
        (
            ContentLimit("section", 4_999, "Notion blocks", notion_block_count),
            ContentLimit("section", 200_000, "bytes of JSON", json_string_bytes),
        ),
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
