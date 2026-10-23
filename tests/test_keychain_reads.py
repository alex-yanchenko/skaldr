import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
import pytest

from skaldr.auth import store
from skaldr.auth.cli import main as auth_main
from skaldr.auth.notion import NotionSession
from skaldr.auth.store import (
    find_notion,
    forget,
    load_jira,
    load_notion,
    require_notion,
    save_jira,
    save_notion_returning_the_replaced,
    stored_notion_sign_ins,
)
from skaldr.cli import main as skaldr_main
from skaldr.publish import ConnectorRegistry
from skaldr.publish.cli import main as publish_main
from skaldr.publish.content import ItemContent
from skaldr.publish.jira import JiraConnector
from skaldr.publish.notion.connector import NotionConnector
from skaldr.publish.slack.connector import SlackConnector
from skaldr.publish_block import NotionTarget
from tests.factories import NOTION_PAGE_ID, make_jira_target, make_notion_target, make_slack_target
from tests.factories.auth_factory import (
    OTHER_WORKSPACE_ID,
    WORKSPACE_ID,
    CountingKeyring,
    InMemoryKeyring,
    legacy_entry_json,
    make_jira_credentials,
    make_notion_credentials,
    make_slack_credentials,
    stored_entry,
)
from tests.factories.jira_factory import FakeJira
from tests.factories.notion_factory import InMemoryNotion
from tests.factories.publish_factory import DOC_ID, write_garden_report
from tests.factories.slack_factory import InMemorySlack

OTHER_JIRA_SITE = "https://other.atlassian.net"
OTHER_SLACK_TEAM = "T0EXAMPLE2"
SECOND_NOTION_PAGE_ID = "fedcba9876543210fedcba9876543210"
Reads = Counter[tuple[str, str]]


@dataclass(frozen=True)
class Document:
    name: str
    services: tuple[str, ...]


DOCUMENTS = (
    Document("notion only", ("notion",)),
    Document("jira only", ("jira",)),
    Document("slack only", ("slack",)),
    Document("all three", ("notion", "jira", "slack")),
)


@dataclass(frozen=True)
class Command:
    name: str
    needs_a_published_document: bool
    run: Callable[[Path, ConnectorRegistry], int]


COMMANDS = (
    Command(
        "publish --apply",
        False,
        lambda path, registry: publish_main(["publish", str(path), "--apply"], registry=registry),
    ),
    Command(
        "publish --apply again",
        True,
        lambda path, registry: publish_main(["publish", str(path), "--apply"], registry=registry),
    ),
    Command(
        "publish (dry run)",
        True,
        lambda path, registry: publish_main(["publish", str(path)], registry=registry),
    ),
    Command("diff", True, lambda path, registry: publish_main(["diff", str(path)], registry=registry)),
    Command("status", True, lambda path, registry: publish_main(["status", str(path)], registry=registry)),
    Command(
        "--check --for notion",
        False,
        lambda path, _registry: skaldr_main(["--check", str(path), "--for", "notion"]),
    ),
)


def _counting_keyring() -> CountingKeyring:
    counting = CountingKeyring()
    keyring.set_keyring(counting)
    assert keyring.get_keyring() is counting
    assert isinstance(counting, InMemoryKeyring)
    return counting


def _sign_in_to_every_service(sign_ins_per_service: int) -> None:
    store.save_notion_returning_the_replaced(make_notion_credentials())
    store.save_jira(make_jira_credentials())
    store.save_slack(make_slack_credentials())
    if sign_ins_per_service == 2:
        store.save_notion_returning_the_replaced(
            make_notion_credentials(workspace_id=OTHER_WORKSPACE_ID, workspace_name="Other Workspace")
        )
        store.save_jira(make_jira_credentials(site=OTHER_JIRA_SITE))
        store.save_slack(make_slack_credentials(team_id=OTHER_SLACK_TEAM, team_name="Other Garden"))


def _targets(services: tuple[str, ...], sign_ins_per_service: int) -> list[dict[str, Any]]:
    several = sign_ins_per_service == 2
    targets: dict[str, dict[str, Any]] = {}
    notion = make_notion_target()
    if several:
        notion["where"] = {**notion["where"], "workspace": WORKSPACE_ID}
    targets["notion"] = notion
    jira = make_jira_target(where={"project": "DEMO", "issue_type": "Task"})
    if several:
        jira["where"] = {**jira["where"], "site": "https://example.atlassian.net"}
    targets["jira"] = jira
    slack = make_slack_target()
    if several:
        slack["where"] = {**slack["where"], "workspace": "T0EXAMPLE1"}
    targets["slack"] = slack
    return [targets[service] for service in services]


def _registry() -> ConnectorRegistry:
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Team plans")
    notion.add_page(SECOND_NOTION_PAGE_ID, "Other plans")
    jira = FakeJira()
    return ConnectorRegistry(
        [
            NotionConnector(http=notion.mock(), sleep=lambda _: None),
            JiraConnector(http_transport=jira.transport(), sleep=jira.sleeps.append),
            SlackConnector(http=InMemorySlack().mock(), sleep=lambda _: None),
        ]
    )


def measured(document: Document, command: Command, sign_ins_per_service: int, directory: Path) -> Reads:
    counting = _counting_keyring()
    _sign_in_to_every_service(sign_ins_per_service)
    path = write_garden_report(
        directory,
        publish={"doc_id": DOC_ID, "targets": _targets(document.services, sign_ins_per_service)},
    )
    registry = _registry()
    if command.needs_a_published_document:
        assert publish_main(["publish", str(path), "--apply"], registry=registry) == 0
    counting.forget_operations()
    assert command.run(path, registry) == 0
    return counting.counts()


def _stored_items(service: str, sign_ins_per_service: int) -> list[str]:
    first = {
        "notion": f"notion:{WORKSPACE_ID}",
        "jira": "jira:https://example.atlassian.net",
        "slack": "slack:T0EXAMPLE1",
    }
    second = {
        "notion": f"notion:{OTHER_WORKSPACE_ID}",
        "jira": f"jira:{OTHER_JIRA_SITE}",
        "slack": f"slack:{OTHER_SLACK_TEAM}",
    }
    return [first[service], *([second[service]] if sign_ins_per_service == 2 else [])]


def each_item_read_once(services: tuple[str, ...], sign_ins_per_service: int) -> Reads:
    reads: Reads = Counter({("get", "index"): 1})
    for service in services:
        reads[("get", service)] += 1
        for item in _stored_items(service, sign_ins_per_service):
            reads[("get", item)] += 1
    return reads


@pytest.mark.parametrize("sign_ins_per_service", [1, 2], ids=["one sign-in", "two sign-ins"])
@pytest.mark.parametrize("command", COMMANDS, ids=[command.name for command in COMMANDS])
@pytest.mark.parametrize("document", DOCUMENTS, ids=[document.name for document in DOCUMENTS])
def test_a_command_reads_each_keychain_item_it_needs_once_and_writes_none(
    document: Document, command: Command, sign_ins_per_service: int, tmp_path: Path
) -> None:
    expected = (
        Counter[tuple[str, str]]()
        if command.name.startswith("--check")
        else each_item_read_once(document.services, sign_ins_per_service)
    )

    assert measured(document, command, sign_ins_per_service, tmp_path) == expected


def _store_what_an_earlier_skaldr_wrote(keychain: InMemoryKeyring) -> dict[tuple[str, str], str]:
    notion = make_notion_credentials()
    jira = make_jira_credentials()
    slack = make_slack_credentials()
    keychain.entries[("skaldr", f"notion:{WORKSPACE_ID}")] = notion.model_dump_json()
    keychain.entries[("skaldr", f"jira:{jira.site}")] = jira.model_dump_json()
    keychain.entries[("skaldr", f"slack:{slack.team_id}")] = slack.model_dump_json()
    keychain.entries[("skaldr", "index")] = json.dumps(
        {
            "jira": [f"jira:{jira.site}"],
            "notion": [f"notion:{WORKSPACE_ID}"],
            "slack": [f"slack:{slack.team_id}"],
        }
    )
    return dict(keychain.entries)


def test_sign_ins_an_earlier_skaldr_saved_load_unchanged_and_the_keychain_is_left_as_it_was(
    tmp_path: Path,
) -> None:
    counting = _counting_keyring()
    saved = _store_what_an_earlier_skaldr_wrote(counting)
    path = write_garden_report(
        tmp_path, publish={"doc_id": DOC_ID, "targets": _targets(("notion", "jira", "slack"), 1)}
    )

    exit_code = publish_main(["publish", str(path), "--apply"], registry=_registry())

    assert (exit_code, counting.entries, counting.counts()[("get", "index")]) == (0, saved, 1)


def test_a_legacy_single_entry_is_migrated_as_before_and_read_once() -> None:
    counting = _counting_keyring()
    notion = make_notion_credentials(workspace_id=None)
    counting.entries[("skaldr", "notion")] = legacy_entry_json(notion)

    with store.reading_each_keychain_item_once():
        loaded = load_notion()

    assert (
        loaded is not None and loaded.credentials,
        counting.entries,
        counting.counts(),
    ) == (
        notion,
        {
            ("skaldr", "notion:unidentified"): notion.model_dump_json(),
            ("skaldr", "index"): json.dumps({"jira": [], "notion": ["notion:unidentified"]}),
        },
        Counter(
            {
                ("get", "notion"): 1,
                ("get", "notion:unidentified"): 1,
                ("get", "index"): 1,
                ("set", "notion:unidentified"): 1,
                ("set", "index"): 1,
                ("delete", "notion"): 1,
            }
        ),
    )


def test_a_save_inside_a_command_is_seen_by_the_next_read_of_the_same_command() -> None:
    _counting_keyring()
    save_jira(make_jira_credentials(api_token="first-token"))

    with store.reading_each_keychain_item_once():
        before = load_jira()
        save_jira(make_jira_credentials(api_token="second-token"))
        after = load_jira()

    assert (before and before.credentials.api_token, after and after.credentials.api_token) == (
        "first-token",
        "second-token",
    )


def test_outside_a_command_every_read_asks_the_keychain() -> None:
    counting = _counting_keyring()
    save_jira(make_jira_credentials())
    counting.forget_operations()

    load_jira()
    load_jira()

    assert counting.counts() == Counter(
        {("get", "index"): 2, ("get", "jira"): 4, ("get", "jira:https://example.atlassian.net"): 2}
    )


def test_forgetting_a_sign_in_that_changed_since_it_was_read_leaves_it_alone() -> None:
    counting = _counting_keyring()
    save_jira(make_jira_credentials(api_token="first-token"))

    with store.reading_each_keychain_item_once():
        entry = store.stored_jira_sign_ins()[0]
        counting.entries[("skaldr", entry.username)] = make_jira_credentials(
            api_token="rotated"
        ).model_dump_json()
        forgotten = forget(entry)

    assert (forgotten, ("skaldr", entry.username) in counting.entries) == (False, True)


def test_a_renewal_inside_a_command_sees_the_token_another_skaldr_stored_meanwhile() -> None:
    counting = _counting_keyring()
    store.save_notion_returning_the_replaced(make_notion_credentials(access_token="first-access"))

    with store.reading_each_keychain_item_once():
        loaded = load_notion()
        counting.entries[("skaldr", f"notion:{WORKSPACE_ID}")] = make_notion_credentials(
            access_token="second-access"
        ).model_dump_json()
        found = find_notion(WORKSPACE_ID, reread=True)

    assert (
        loaded and loaded.credentials.access_token,
        found and found.credentials and found.credentials.access_token,
    ) == (
        "first-access",
        "second-access",
    )


def test_a_save_inside_a_command_reads_what_it_replaces_afresh() -> None:
    counting = _counting_keyring()
    store.save_notion_returning_the_replaced(make_notion_credentials(access_token="first-access"))

    with store.reading_each_keychain_item_once():
        stored_notion_sign_ins()
        counting.entries[("skaldr", f"notion:{WORKSPACE_ID}")] = make_notion_credentials(
            access_token="second-access"
        ).model_dump_json()
        replacement = save_notion_returning_the_replaced(make_notion_credentials(access_token="third-access"))

    assert replacement.replaced == stored_entry(
        "notion", f"notion:{WORKSPACE_ID}", make_notion_credentials(access_token="second-access")
    )


def test_a_session_renewing_inside_a_command_takes_the_token_another_skaldr_stored_meanwhile() -> None:
    counting = _counting_keyring()
    store.save_notion_returning_the_replaced(make_notion_credentials(access_token="first-access"))

    with store.reading_each_keychain_item_once():
        session = NotionSession(require_notion())
        counting.entries[("skaldr", f"notion:{WORKSPACE_ID}")] = make_notion_credentials(
            access_token="second-access"
        ).model_dump_json()
        session.renew()

    assert session.access_token == "second-access"


def test_nested_commands_share_the_reads_of_the_outer_one() -> None:
    counting = _counting_keyring()
    save_jira(make_jira_credentials())
    counting.forget_operations()

    with store.reading_each_keychain_item_once():
        load_jira()
        with store.reading_each_keychain_item_once():
            load_jira()
        load_jira()

    assert counting.counts() == each_item_read_once(("jira",), 1)


def test_a_command_that_fails_leaves_nothing_remembered_for_the_next_read() -> None:
    counting = _counting_keyring()
    save_jira(make_jira_credentials())

    with pytest.raises(RuntimeError), store.reading_each_keychain_item_once():
        load_jira()
        raise RuntimeError("the command failed")
    counting.forget_operations()
    load_jira()

    assert counting.counts() == Counter(
        {("get", "index"): 1, ("get", "jira"): 2, ("get", "jira:https://example.atlassian.net"): 1}
    )


def test_several_targets_of_one_service_share_the_reads_of_its_sign_ins(tmp_path: Path) -> None:
    counting = _counting_keyring()
    _sign_in_to_every_service(1)
    second_target = make_notion_target(where={"parent_page": SECOND_NOTION_PAGE_ID})
    path = write_garden_report(
        tmp_path, publish={"doc_id": DOC_ID, "targets": [make_notion_target(), second_target]}
    )
    counting.forget_operations()

    exit_code = publish_main(["publish", str(path), "--apply"], registry=_registry())

    assert (exit_code, counting.counts()) == (0, each_item_read_once(("notion",), 1))


def test_a_renewed_token_is_the_only_write_a_command_makes() -> None:
    counting = _counting_keyring()
    store.save_notion_returning_the_replaced(make_notion_credentials(access_token="lapsed-access"))
    notion = InMemoryNotion()
    notion.add_page(NOTION_PAGE_ID, "Team plans")
    target = NotionTarget.model_validate(make_notion_target())
    counting.forget_operations()

    with store.reading_each_keychain_item_once():
        transport = NotionConnector(http=notion.mock(), sleep=lambda _: None).open_transport(target)
        transport.read_item(NOTION_PAGE_ID, ItemContent(title=""))

    writes = Counter(
        {operation: count for operation, count in counting.counts().items() if operation[0] != "get"}
    )
    assert writes == Counter({("set", f"notion:{WORKSPACE_ID}"): 1})


def test_listing_a_sign_in_found_by_name_keeps_an_index_entry_another_skaldr_added_meanwhile() -> None:
    counting = _counting_keyring()
    store.save_notion_returning_the_replaced(make_notion_credentials())
    unlisted = make_notion_credentials(workspace_id=OTHER_WORKSPACE_ID)
    other_skaldrs_entry = f"jira:{OTHER_JIRA_SITE}"

    with store.reading_each_keychain_item_once():
        stored_notion_sign_ins()
        counting.entries[("skaldr", f"notion:{OTHER_WORKSPACE_ID}")] = unlisted.model_dump_json()
        counting.entries[("skaldr", "index")] = json.dumps(
            {"jira": [other_skaldrs_entry], "notion": [f"notion:{WORKSPACE_ID}"]}
        )
        find_notion(OTHER_WORKSPACE_ID)

    assert json.loads(counting.entries[("skaldr", "index")]) == {
        "jira": [other_skaldrs_entry],
        "notion": [f"notion:{WORKSPACE_ID}", f"notion:{OTHER_WORKSPACE_ID}"],
    }


def test_forgetting_a_sign_in_keeps_an_index_entry_another_skaldr_added_meanwhile() -> None:
    counting = _counting_keyring()
    save_jira(make_jira_credentials())
    other_skaldrs_entry = f"notion:{OTHER_WORKSPACE_ID}"

    with store.reading_each_keychain_item_once():
        entry = store.stored_jira_sign_ins()[0]
        counting.entries[("skaldr", "index")] = json.dumps(
            {"jira": [entry.username], "notion": [other_skaldrs_entry]}
        )
        forgotten = forget(entry)

    assert (forgotten, json.loads(counting.entries[("skaldr", "index")])) == (
        True,
        {"jira": [], "notion": [other_skaldrs_entry]},
    )


def test_auth_status_reads_the_index_once_and_each_item_it_lists_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    counting = _counting_keyring()
    _sign_in_to_every_service(2)
    counting.forget_operations()

    exit_code = auth_main(["status"])

    assert (exit_code, counting.counts()) == (0, each_item_read_once(("notion", "jira", "slack"), 2))
    capsys.readouterr()
