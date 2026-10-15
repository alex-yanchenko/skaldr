import json
import re
from pathlib import Path
from typing import Any

import pytest

from skaldr.errors import ConnectorError
from skaldr.publish import ConnectorRegistry
from skaldr.publish.cli import main
from skaldr.publish.drafts import draft_targets
from skaldr.publish.engine import Applied, ApplyOutcome, apply_publish, dry_run_publish, prepare_publish
from skaldr.publish.jira import JiraConnector
from skaldr.publish.links import LinkStep, describe_links, paired_items
from skaldr.publish.notion.connector import NotionConnector
from skaldr.publish.plan import ItemRef
from skaldr.publish.state import load_state, save_state, state_path_for
from skaldr.publish.transport import ShownLink
from skaldr.publish_block import JiraTarget, NotionTarget
from tests.factories.auth_factory import make_jira_credentials, make_notion_credentials, seed_notion
from tests.factories.jira_factory import FakeJira
from tests.factories.notion_factory import InMemoryNotion, numbered_id
from tests.factories.publish_factory import (
    DOC_ID,
    DROPPED_AFTER_WRITE,
    FAKE_ITEM_ADDRESS,
    TARGET_LABEL,
    FakeTransport,
    authored_garden,
    fake_registry,
    make_garden_blocks,
    write_garden_report,
)
from tests.factories.report_factory import (
    NOTION_PAGE_ID,
    NOTION_PAGE_URL,
    make_jira_target,
    make_notion_target,
)

JIRA_LABEL = "jira project PLAN under no parent issue"
OPS_LABEL = "jira project OPS under no parent issue"
OTHER_PAGE_ID = "fedcba9876543210fedcba9876543210"
OTHER_LABEL = f"notion page {OTHER_PAGE_ID}"
NOTION_DOCUMENT = ItemRef(TARGET_LABEL, None)
NOTION_TOOLS = ItemRef(TARGET_LABEL, "tools")
JIRA_DOCUMENT = ItemRef(JIRA_LABEL, None)
JIRA_TOOLS = ItemRef(JIRA_LABEL, "tools")


def _notion(**target: Any) -> dict[str, Any]:
    return make_notion_target(where={"parent_page": NOTION_PAGE_URL}, **target)


def _jira(project: str = "PLAN", **target: Any) -> dict[str, Any]:
    return make_jira_target(where={"project": project, "issue_type": "Task"}, **target)


def _publish_block(*targets: dict[str, Any]) -> dict[str, Any]:
    return {"doc_id": DOC_ID, "targets": list(targets)}


BOTH_SPLIT = _publish_block(_notion(split=["tools"]), _jira(split=["tools"]))


def _registry(transport: FakeTransport) -> Any:
    return fake_registry(transport, target_types=(NotionTarget, JiraTarget))


def _publish(path: Path, transport: FakeTransport) -> ApplyOutcome:
    return apply_publish(prepare_publish(path, _registry(transport)))


def _shown(item_id: str, title: str) -> ShownLink:
    return ShownLink(service="jira", url=f"{FAKE_ITEM_ADDRESS}{item_id}", title=title)


def _page(item_id: str, title: str) -> ShownLink:
    return ShownLink(service="notion", url=f"{FAKE_ITEM_ADDRESS}{item_id}", title=title)


def _links_of(transport: FakeTransport) -> dict[str, tuple[ShownLink, ...]]:
    return {item_id: item.links for item_id, item in transport.items.items()}


@pytest.mark.parametrize(
    ("publish", "pairs"),
    [
        pytest.param(
            _publish_block(_notion(), _jira()),
            {
                NOTION_DOCUMENT: (JIRA_DOCUMENT,),
                JIRA_DOCUMENT: (NOTION_DOCUMENT,),
            },
            id="the-documents",
        ),
        pytest.param(
            BOTH_SPLIT,
            {
                NOTION_DOCUMENT: (JIRA_DOCUMENT,),
                NOTION_TOOLS: (JIRA_TOOLS,),
                JIRA_DOCUMENT: (NOTION_DOCUMENT,),
                JIRA_TOOLS: (NOTION_TOOLS,),
            },
            id="split-sections",
        ),
        pytest.param(
            _publish_block(_notion(split=["tools", "planting"]), _jira(split=["tools"])),
            {
                NOTION_DOCUMENT: (JIRA_DOCUMENT,),
                NOTION_TOOLS: (JIRA_TOOLS,),
                ItemRef(TARGET_LABEL, "planting"): (),
                JIRA_DOCUMENT: (NOTION_DOCUMENT,),
                JIRA_TOOLS: (NOTION_TOOLS,),
            },
            id="a-section-split-in-one-target-only",
        ),
        pytest.param(
            _publish_block(
                _notion(), make_notion_target(where={"parent_page": OTHER_PAGE_ID}), _jira(), _jira("OPS")
            ),
            {
                NOTION_DOCUMENT: (JIRA_DOCUMENT, ItemRef(OPS_LABEL, None)),
                ItemRef(OTHER_LABEL, None): (JIRA_DOCUMENT, ItemRef(OPS_LABEL, None)),
                JIRA_DOCUMENT: (NOTION_DOCUMENT, ItemRef(OTHER_LABEL, None)),
                ItemRef(OPS_LABEL, None): (NOTION_DOCUMENT, ItemRef(OTHER_LABEL, None)),
            },
            id="two-targets-of-each-service",
        ),
        pytest.param(
            _publish_block(
                _notion(split=["tools"]), make_notion_target(where={"parent_page": OTHER_PAGE_ID})
            ),
            {NOTION_DOCUMENT: (), NOTION_TOOLS: (), ItemRef(OTHER_LABEL, None): ()},
            id="one-service-only",
        ),
    ],
)
def test_items_pair_across_services_by_the_part_of_the_document_they_hold(
    publish: dict[str, Any], pairs: dict[ItemRef, tuple[ItemRef, ...]]
) -> None:
    drafts = draft_targets(authored_garden(publish=publish), _registry(FakeTransport()))

    assert paired_items(drafts) == pairs


FIRST_LINKS = (
    "link     document to jira project PLAN under no parent issue, document",
    "link     section tools to jira project PLAN under no parent issue, section tools",
    f"link     document to {TARGET_LABEL}, document",
    f"link     section tools to {TARGET_LABEL}, section tools",
)


def test_a_first_publish_links_each_notion_page_and_jira_issue_after_both_exist(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path, publish=BOTH_SPLIT)
    steps: list[tuple[str, str]] = []

    outcome = apply_publish(
        prepare_publish(path, _registry(transport)), on_step=lambda target, step: steps.append((target, step))
    )
    state = load_state(state_path_for(path), DOC_ID)

    assert (outcome, steps[-4:], _links_of(transport), transport.writes()[-4:]) == (
        Applied(
            (
                'create   document "Garden handbook"',
                'create   section tools "Tools"',
                'create   document "Garden handbook"',
                'create   section tools "Tools"',
                *FIRST_LINKS,
            )
        ),
        [
            (TARGET_LABEL, FIRST_LINKS[0]),
            (TARGET_LABEL, FIRST_LINKS[1]),
            (JIRA_LABEL, FIRST_LINKS[2]),
            (JIRA_LABEL, FIRST_LINKS[3]),
        ],
        {
            "page-1": (_shown("page-3", "Garden handbook"),),
            "page-2": (_shown("page-4", "Tools"),),
            "page-3": (_page("page-1", "Garden handbook"),),
            "page-4": (_page("page-2", "Tools"),),
        },
        [
            ("write_links", "page-1", "Garden handbook"),
            ("write_links", "page-2", "Tools"),
            ("write_links", "page-3", "Garden handbook"),
            ("write_links", "page-4", "Tools"),
        ],
    )
    assert {
        label: {section: item.links for section, item in target.held_items()}
        for label, target in state.targets.items()
    } == {
        TARGET_LABEL: {
            None: [_shown("page-3", "Garden handbook")],
            "tools": [_shown("page-4", "Tools")],
        },
        JIRA_LABEL: {
            None: [_page("page-1", "Garden handbook")],
            "tools": [_page("page-2", "Tools")],
        },
    }


def test_publishing_again_with_every_link_in_place_writes_nothing(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path, publish=BOTH_SPLIT)
    _publish(path, transport)
    transport.forget_calls()

    outcome = _publish(path, transport)

    assert (outcome, transport.writes()) == (Applied(()), [])


def test_a_state_file_that_lost_the_links_in_place_is_corrected_without_writing_them(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path, publish=BOTH_SPLIT)
    _publish(path, transport)
    published = load_state(state_path_for(path), DOC_ID)
    forgotten = {
        label: target.model_copy(
            update={
                "document": None
                if target.document is None
                else target.document.model_copy(update={"links": []}),
                "sections": {
                    section: item.model_copy(update={"links": []})
                    for section, item in target.sections.items()
                },
            }
        )
        for label, target in published.targets.items()
    }
    save_state(state_path_for(path), published.model_copy(update={"targets": forgotten}))
    transport.forget_calls()

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), load_state(state_path_for(path), DOC_ID)) == (
        Applied(()),
        [],
        published,
    )


def test_the_dry_run_of_a_first_publish_lists_the_links_it_would_write(tmp_path: Path) -> None:
    path = write_garden_report(tmp_path, publish=BOTH_SPLIT)

    dry_run = dry_run_publish(prepare_publish(path, _registry(FakeTransport())))

    assert describe_links(dry_run.links) == [
        "links: 4 to link, 0 to unlink",
        f"  {TARGET_LABEL}: {FIRST_LINKS[0]}",
        f"  {TARGET_LABEL}: {FIRST_LINKS[1]}",
        f"  {JIRA_LABEL}: {FIRST_LINKS[2]}",
        f"  {JIRA_LABEL}: {FIRST_LINKS[3]}",
    ]


def test_a_link_deleted_by_hand_shows_in_the_dry_run_and_the_next_publish_writes_it_back(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path, publish=BOTH_SPLIT)
    _publish(path, transport)
    transport.link_by_hand("page-3", ())
    transport.forget_calls()

    dry_run = dry_run_publish(prepare_publish(path, _registry(transport)))
    outcome = _publish(path, transport)

    assert (dry_run.links, outcome, transport.writes(), transport.items["page-3"].links) == (
        (LinkStep(JIRA_DOCUMENT, "link", f"{TARGET_LABEL}, document"),),
        Applied((FIRST_LINKS[2],)),
        [("write_links", "page-3", "Garden handbook")],
        (_page("page-1", "Garden handbook"),),
    )


def test_a_dry_run_writes_no_link_and_leaves_the_state_file_alone(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path, publish=BOTH_SPLIT)
    _publish(path, transport)
    transport.link_by_hand("page-3", ())
    state_before = state_path_for(path).read_bytes()
    transport.forget_calls()

    dry_run_publish(prepare_publish(path, _registry(transport)))

    assert (transport.writes(), state_path_for(path).read_bytes()) == ([], state_before)


def _published_then_rewritten(tmp_path: Path, transport: FakeTransport, publish: dict[str, Any]) -> Path:
    path = write_garden_report(tmp_path, publish=BOTH_SPLIT)
    _publish(path, transport)
    write_garden_report(tmp_path, publish=publish)
    transport.forget_calls()
    return path


def test_a_jira_target_added_to_a_published_document_is_linked_once_its_issue_exists(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path, publish=_publish_block(_notion()))
    _publish(path, transport)
    write_garden_report(tmp_path, publish=_publish_block(_notion(), _jira()))
    transport.forget_calls()

    dry_run = dry_run_publish(prepare_publish(path, _registry(transport)))
    outcome = _publish(path, transport)

    assert (dry_run.links, outcome, _links_of(transport)) == (
        (
            LinkStep(NOTION_DOCUMENT, "link", f"{JIRA_LABEL}, document"),
            LinkStep(JIRA_DOCUMENT, "link", f"{TARGET_LABEL}, document"),
        ),
        Applied(
            (
                'create   document "Garden handbook"',
                f"link     document to {JIRA_LABEL}, document",
                f"link     document to {TARGET_LABEL}, document",
            )
        ),
        {
            "page-1": (_shown("page-2", "Garden handbook"),),
            "page-2": (_page("page-1", "Garden handbook"),),
        },
    )


def test_removing_the_jira_target_archives_its_issues_and_drops_them_from_each_notion_stamp(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, _publish_block(_notion(split=["tools"])))

    outcome = _publish(path, transport)
    state = load_state(state_path_for(path), DOC_ID)

    assert (outcome, _links_of(transport)["page-1"], _links_of(transport)["page-2"]) == (
        Applied(
            (
                "archive  section tools (page-4)",
                "archive  document (page-3)",
                "unlink   document from Garden handbook",
                "unlink   section tools from Tools",
            )
        ),
        (),
        (),
    )
    assert [item.links for _, item in state.targets[TARGET_LABEL].held_items()] == [[], []]


def test_a_link_sent_by_a_run_that_stopped_after_sending_it_is_removed_once_its_pair_ends(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    path = write_garden_report(tmp_path, publish=_publish_block(_notion(), _jira()))
    transport.drop_the_connection_after_write(4)
    with pytest.raises(ConnectorError, match=f"^{re.escape(DROPPED_AFTER_WRITE)}$"):
        _publish(path, transport)
    transport.stop_failing()
    write_garden_report(tmp_path, publish=_publish_block(_jira()))

    outcome = _publish(path, transport)

    assert (outcome, _links_of(transport)) == (
        Applied(("archive  document (page-1)", "unlink   document from Garden handbook")),
        {"page-1": (_shown("page-2", "Garden handbook"),), "page-2": ()},
    )


def test_a_section_no_longer_split_in_jira_unlinks_only_that_section(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, _publish_block(_notion(split=["tools"]), _jira()))

    outcome = _publish(path, transport)

    assert (outcome.steps[-2:] if isinstance(outcome, Applied) else outcome, _links_of(transport)) == (
        ("archive  section tools (page-4)", "unlink   section tools from Tools"),
        {
            "page-1": (_shown("page-3", "Garden handbook"),),
            "page-2": (),
            "page-3": (_page("page-1", "Garden handbook"),),
            "page-4": (_page("page-2", "Tools"),),
        },
    )


def test_releasing_a_page_written_into_unlinks_its_issue_and_takes_the_links_off_the_page(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    written_into = make_notion_target(where={"page": NOTION_PAGE_ID})
    path = write_garden_report(tmp_path, publish=_publish_block(written_into, _jira()))
    _publish(path, transport)
    write_garden_report(tmp_path, publish=_publish_block(_jira()))
    transport.forget_calls()

    outcome = _publish(path, transport)

    assert (outcome, _links_of(transport)) == (
        Applied((f"release  document ({NOTION_PAGE_ID})", "unlink   document from Garden handbook")),
        {NOTION_PAGE_ID: (), "page-2": ()},
    )


def test_removing_the_notion_target_unlinks_each_jira_issue(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, _publish_block(_jira(split=["tools"])))

    outcome = _publish(path, transport)

    assert (outcome, _links_of(transport)["page-3"], _links_of(transport)["page-4"]) == (
        Applied(
            (
                "archive  section tools (page-2)",
                "archive  document (page-1)",
                "unlink   document from Garden handbook",
                "unlink   section tools from Tools",
            )
        ),
        (),
        (),
    )


def test_a_retitled_item_updates_the_link_to_it_in_place(tmp_path: Path) -> None:
    transport = FakeTransport()
    blocks = make_garden_blocks(tools_title="Garden tools")
    path = write_garden_report(tmp_path, publish=BOTH_SPLIT)
    _publish(path, transport)
    write_garden_report(tmp_path, publish=BOTH_SPLIT, blocks=blocks)
    transport.forget_calls()

    outcome = _publish(path, transport)

    assert (outcome.steps[-2:] if isinstance(outcome, Applied) else outcome, _links_of(transport)) == (
        (
            "link     section tools to jira project PLAN under no parent issue, section tools",
            f"link     section tools to {TARGET_LABEL}, section tools",
        ),
        {
            "page-1": (_shown("page-3", "Garden handbook"),),
            "page-2": (_shown("page-4", "Garden tools"),),
            "page-3": (_page("page-1", "Garden handbook"),),
            "page-4": (_page("page-2", "Garden tools"),),
        },
    )


DOCUMENT_PAGE = numbered_id(1).replace("-", "")
TOOLS_PAGE = numbered_id(2).replace("-", "")
DEMO_LABEL = "jira project DEMO under no parent issue"
LINKED_BOTH_WAYS = _publish_block(_notion(split=["tools"]), _jira("DEMO", split=["tools"]))


def _services() -> tuple[InMemoryNotion, FakeJira, ConnectorRegistry]:
    seed_notion(make_notion_credentials())
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_URL, "Team plans")
    jira = FakeJira()
    registry = ConnectorRegistry(
        [
            NotionConnector(http=notion.mock(), sleep=lambda _: None),
            JiraConnector(
                sign_in=lambda _site: make_jira_credentials(),
                http_transport=jira.transport(),
                sleep=jira.sleeps.append,
            ),
        ]
    )
    return notion, jira, registry


def _stamps(notion: InMemoryNotion) -> list[str]:
    return [
        next(line for line in reversed(notion.markdown_of(page).splitlines()) if line.startswith("Published"))
        for page in (DOCUMENT_PAGE, TOOLS_PAGE)
    ]


def _remote_link_bodies(jira: FakeJira) -> list[tuple[str, Any]]:
    return [
        (request.url.path, json.loads(request.content))
        for request in jira.requests
        if request.method == "POST" and request.url.path.endswith("/remotelink")
    ]


def test_publishing_to_notion_and_jira_links_each_page_and_issue_both_ways_and_again_sends_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notion, jira, registry = _services()
    path = write_garden_report(tmp_path, publish=LINKED_BOTH_WAYS)

    first = main(["publish", str(path), "--apply"], registry=registry)
    first_out = capsys.readouterr().out.splitlines()
    notion_writes, jira_writes = len(notion.writes()), len(jira.requests)
    again = main(["publish", str(path), "--apply"], registry=registry)

    assert (first, first_out[-5:], _stamps(notion), _remote_link_bodies(jira)) == (
        0,
        [
            f"{TARGET_LABEL}: link     document to {DEMO_LABEL}, document",
            f"{TARGET_LABEL}: link     section tools to {DEMO_LABEL}, section tools",
            f"{DEMO_LABEL}: link     document to {TARGET_LABEL}, document",
            f"{DEMO_LABEL}: link     section tools to {TARGET_LABEL}, section tools",
            f"Published 8 steps. The publish state is in {state_path_for(path)}.",
        ],
        [
            "Published with skaldr from document garden-handbook · Jira "
            '[DEMO-1](https://example.atlassian.net/browse/DEMO-1) {color="gray"}',
            "Published with skaldr from document garden-handbook, section tools · Jira "
            '[DEMO-2](https://example.atlassian.net/browse/DEMO-2) {color="gray"}',
        ],
        [
            (
                "/rest/api/3/issue/DEMO-1/remotelink",
                {
                    "globalId": f"skaldr:garden-handbook:document:notion:{DOCUMENT_PAGE}",
                    "object": {"url": f"https://www.notion.so/{DOCUMENT_PAGE}", "title": "Garden handbook"},
                },
            ),
            (
                "/rest/api/3/issue/DEMO-2/remotelink",
                {
                    "globalId": f"skaldr:garden-handbook:section:tools:notion:{TOOLS_PAGE}",
                    "object": {"url": f"https://www.notion.so/{TOOLS_PAGE}", "title": "Tools"},
                },
            ),
        ],
    )
    assert (
        again,
        capsys.readouterr().out.splitlines()[-1],
        notion.writes()[notion_writes:],
        [call for call in jira.calls()[jira_writes:] if call[0] != "GET"],
    ) == (0, "Nothing to publish: every item matches the YAML.", [], [])


def _markdown_reads(notion: InMemoryNotion) -> list[str]:
    return [request.url.path for request in notion.requests if request.url.path.endswith("/markdown")]


def test_planning_the_links_reads_no_notion_page_again_in_a_dry_run_or_an_apply(tmp_path: Path) -> None:
    notion, _, registry = _services()
    path = write_garden_report(tmp_path, publish=LINKED_BOTH_WAYS)
    main(["publish", str(path), "--apply"], registry=registry)
    notion.requests.clear()

    main(["publish", str(path)], registry=registry)
    dry_run_reads = _markdown_reads(notion)
    notion.requests.clear()
    main(["publish", str(path), "--apply"], registry=registry)

    each_page_once = [f"/v1/pages/{DOCUMENT_PAGE}/markdown", f"/v1/pages/{TOOLS_PAGE}/markdown"]
    assert (dry_run_reads, _markdown_reads(notion)) == (each_page_once, each_page_once)


def test_removing_the_jira_target_deletes_its_remote_links_and_drops_the_issues_from_the_stamps(
    tmp_path: Path,
) -> None:
    notion, jira, registry = _services()
    path = write_garden_report(tmp_path, publish=LINKED_BOTH_WAYS)
    main(["publish", str(path), "--apply"], registry=registry)
    write_garden_report(tmp_path, publish=_publish_block(_notion(split=["tools"])))

    exit_code = main(["publish", str(path), "--apply"], registry=registry)

    assert (
        exit_code,
        _stamps(notion),
        jira.issues["DEMO-1"].remote_links,
        jira.issues["DEMO-2"].remote_links,
    ) == (
        0,
        [
            'Published with skaldr from document garden-handbook {color="gray"}',
            'Published with skaldr from document garden-handbook, section tools {color="gray"}',
        ],
        [],
        [],
    )


def test_the_dry_run_prints_the_links_after_the_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_garden_report(tmp_path, publish=_publish_block(_notion(), _jira()))

    exit_code = main(["publish", str(path)], registry=_registry(FakeTransport()))

    assert (exit_code, capsys.readouterr().out.splitlines()) == (
        0,
        [
            f"{TARGET_LABEL}: 1 to create, 0 to update, 0 to archive",
            '  create   document "Garden handbook"',
            f"{JIRA_LABEL}: 1 to create, 0 to update, 0 to archive",
            '  create   document "Garden handbook"',
            "links: 2 to link, 0 to unlink",
            f"  {TARGET_LABEL}: link     document to {JIRA_LABEL}, document",
            f"  {JIRA_LABEL}: link     document to {TARGET_LABEL}, document",
            f"Dry run: nothing was sent. Publish with `skaldr publish {path} --apply`.",
        ],
    )
