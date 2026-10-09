import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from skaldr.auth.store import save_jira
from skaldr.errors import ConnectorError, PublishError
from skaldr.export.adf import JIRA_DESCRIPTION_LIMIT, render_adf_regions
from skaldr.export.lower import lower_report
from skaldr.models import parse_report
from skaldr.publish import ConnectorRegistry, ContentLimit
from skaldr.publish.cli import installed_connectors
from skaldr.publish.content import ItemContent
from skaldr.publish.engine import Applied, ApplyOutcome, Refused, apply_publish, prepare_publish
from skaldr.publish.jira import JiraConnector
from skaldr.publish.jira.description import as_blocks, description_length, section_text
from skaldr.publish_block import JiraTarget
from tests.factories import make_jira_target
from tests.factories.auth_factory import basic_auth_header, make_jira_credentials
from tests.factories.jira_factory import DONE, SITE, FakeJira
from tests.factories.publish_factory import (
    DOC_ID,
    make_garden_blocks,
    make_garden_report,
    write_garden_report,
)

TARGET_LABEL = "jira project DEMO under no parent issue"


def _exactly(message: str) -> str:
    return f"^{re.escape(message)}$"


def _connector(jira: FakeJira) -> JiraConnector:
    return JiraConnector(
        sign_in=lambda _site: make_jira_credentials(),
        http_transport=jira.transport(),
        sleep=jira.sleeps.append,
    )


def _jira_where() -> dict[str, Any]:
    return {"project": "DEMO", "issue_type": "Task", "fields": {"labels": ["garden"]}}


def _jira_publish(**target: Any) -> dict[str, Any]:
    return {"doc_id": DOC_ID, "targets": [{"to": "jira", "where": _jira_where(), **target}]}


def _publish(path: Path, jira: FakeJira, *, overwrite: bool = False) -> ApplyOutcome:
    registry = ConnectorRegistry([_connector(jira)])
    return apply_publish(prepare_publish(path, registry), overwrite=overwrite)


def _writes(jira: FakeJira) -> list[tuple[str, str]]:
    return [call for call in jira.calls() if call[0] != "GET"]


def test_skaldr_ships_a_jira_connector_and_no_notion_one_yet() -> None:
    registry = installed_connectors()

    with pytest.raises(ConnectorError, match=r"^no connector publishes to notion$"):
        registry.for_service("notion")
    assert isinstance(registry.for_service("jira"), JiraConnector)


def test_the_connector_replaces_whole_descriptions_never_writes_into_an_issue_and_caps_the_size() -> None:
    connector = JiraConnector()
    target = JiraTarget.model_validate(
        make_jira_target(where={"project": "DEMO", "issue_type": "Task", "parent": "DEMO-4"})
    )

    assert (
        connector.target_type,
        connector.writes,
        connector.existing_item_id(target),
        connector.limits,
    ) == (
        JiraTarget,
        "content",
        None,
        (ContentLimit("item", JIRA_DESCRIPTION_LIMIT, "characters of ADF", description_length),),
    )


def test_each_region_renders_as_its_adf_blocks() -> None:
    report = parse_report(make_garden_report(publish=_jira_publish()))
    page = lower_report(report)

    assert JiraConnector().render_regions(report, page) == tuple(
        section_text(as_blocks(blocks)) for blocks in render_adf_regions(page)
    )


def test_opening_a_transport_without_a_jira_sign_in_says_how_to_sign_in() -> None:
    target = JiraTarget.model_validate(make_jira_target())

    with pytest.raises(ConnectorError, match=_exactly("Not signed in to Jira; run `skaldr auth jira`")):
        JiraConnector().open_transport(target)


def test_the_transport_signs_in_with_the_jira_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_SITE", SITE)
    monkeypatch.setenv("JIRA_EMAIL", "builder@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "ci-token")
    jira = FakeJira()
    jira.seed("DEMO-1", summary="Garden handbook")

    JiraConnector(http_transport=jira.transport()).open_transport(
        JiraTarget.model_validate(make_jira_target())
    ).read_item("DEMO-1", ItemContent(title=""))

    assert {request.headers["authorization"] for request in jira.requests} == {
        basic_auth_header("builder@example.com", "ci-token")
    }


OTHER_SITE = "https://other.atlassian.net"


def _signed_in_to(*sites: str) -> None:
    for site in sites:
        save_jira(make_jira_credentials(site=site, api_token=f"token-for-{site.removeprefix('https://')}"))


def _authorization_sent_for(site: str | None) -> set[str | None]:
    jira = FakeJira()
    jira.seed("DEMO-1", summary="Garden handbook")
    where = {"project": "DEMO", "issue_type": "Task", **({} if site is None else {"site": site})}
    target = JiraTarget.model_validate(make_jira_target(where=where))

    JiraConnector(http_transport=jira.transport()).open_transport(target).read_item(
        "DEMO-1", ItemContent(title="")
    )

    return {request.headers["authorization"] for request in jira.requests}


def test_a_target_without_a_site_uses_the_one_jira_sign_in() -> None:
    _signed_in_to(SITE)

    assert _authorization_sent_for(None) == {
        basic_auth_header("reader@example.com", "token-for-example.atlassian.net")
    }


def test_several_jira_sign_ins_and_no_site_on_the_target_name_the_key_to_set() -> None:
    _signed_in_to(SITE, OTHER_SITE)
    target = JiraTarget.model_validate(make_jira_target())

    with pytest.raises(
        ConnectorError,
        match=_exactly(
            f"Signed in to several Jira sites ({SITE}, {OTHER_SITE}); "
            "name one with `site` in the target's `where`"
        ),
    ):
        JiraConnector().open_transport(target)


def test_several_jira_sign_ins_and_a_site_on_the_target_use_that_site() -> None:
    _signed_in_to(SITE, OTHER_SITE)

    assert _authorization_sent_for("other.atlassian.net") == {
        basic_auth_header("reader@example.com", "token-for-other.atlassian.net")
    }


def test_a_site_with_no_jira_sign_in_lists_the_sites_that_are_signed_in() -> None:
    _signed_in_to(SITE, OTHER_SITE)
    target = JiraTarget.model_validate(
        make_jira_target(
            where={"project": "DEMO", "issue_type": "Task", "site": "https://third.atlassian.net"}
        )
    )

    with pytest.raises(
        ConnectorError,
        match=_exactly(
            "Not signed in to Jira at https://third.atlassian.net; "
            f"signed in to {SITE}, {OTHER_SITE}; run `skaldr auth jira` to add it"
        ),
    ):
        JiraConnector().open_transport(target)


def test_the_transport_reads_each_field_in_the_shape_the_target_or_an_override_writes_it() -> None:
    jira = FakeJira()
    jira.seed("DEMO-1", summary="Tools", priority={"name": "Low", "id": "4"}, components=[{"name": "Beds"}])
    where = {"project": "DEMO", "issue_type": "Task", "fields": {"priority": {"name": "High"}}}
    target = JiraTarget.model_validate(
        make_jira_target(
            where=where, split=["tools"], overrides={"tools": {"fields": {"components": [{"name": "Beds"}]}}}
        )
    )

    read = (
        _connector(jira)
        .open_transport(target)
        .read_item("DEMO-1", ItemContent(title="", fields={"priority": None, "components": None}))
    )

    assert read.comparable.fields == {"priority": {"name": "Low"}, "components": [{"name": "Beds"}]}


def test_publishing_creates_the_document_issue_then_each_split_section_under_it(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(tmp_path, publish=_jira_publish(split=["tools"]))

    outcome = _publish(path, jira)

    document, tools = jira.issues["DEMO-1"], jira.issues["DEMO-2"]
    assert (
        outcome,
        _writes(jira),
        (document.fields["summary"], document.fields["labels"], document.properties["skaldr.stamp"]),
        (tools.fields["summary"], tools.fields["parent"], tools.properties["skaldr.stamp"]),
    ) == (
        Applied(('create   document "Garden handbook"', 'create   section tools "Tools"')),
        [("POST", "/rest/api/3/issue"), ("POST", "/rest/api/3/issue")],
        (
            "Garden handbook",
            ["garden", "skaldr-garden-handbook"],
            {"doc_id": DOC_ID, "section_id": None, "commented": False, "archived": False},
        ),
        (
            "Tools",
            {"key": "DEMO-1"},
            {"doc_id": DOC_ID, "section_id": "tools", "commented": False, "archived": False},
        ),
    )


def test_publishing_again_unchanged_writes_nothing(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(tmp_path, publish=_jira_publish(split=["tools"]))
    _publish(path, jira)
    jira.forget_requests()

    assert (_publish(path, jira), _writes(jira)) == (Applied(()), [])


def test_a_changed_section_rewrites_its_issues_description_once(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(tmp_path, publish=_jira_publish(split=["tools"]))
    _publish(path, jira)
    write_garden_report(
        tmp_path, publish=_jira_publish(split=["tools"]), blocks=make_garden_blocks(planting="Sow in May.")
    )
    jira.forget_requests()

    outcome = _publish(path, jira)

    assert (outcome, _writes(jira), _publish(path, jira)) == (
        Applied(("update   document: planting (blocks[2])",)),
        [("PUT", "/rest/api/3/issue/DEMO-1")],
        Applied(()),
    )


def _edit_planting_by_hand(jira: FakeJira) -> None:
    description = jira.issues["DEMO-1"].fields["description"]
    if not isinstance(description, dict) or not isinstance(description["content"], list):
        raise TypeError("DEMO-1 has no description")
    content: list[JsonValue] = [
        *description["content"][:-1],
        {"type": "paragraph", "content": [{"type": "text", "text": "Sow in June."}]},
    ]
    jira.edit_by_hand("DEMO-1", description={**description, "content": content})


def test_a_description_edited_in_jira_stops_the_publish_until_overwritten(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(tmp_path, publish=_jira_publish(split=["tools"]))
    _publish(path, jira)
    write_garden_report(
        tmp_path, publish=_jira_publish(split=["tools"]), blocks=make_garden_blocks(planting="Sow in May.")
    )
    _edit_planting_by_hand(jira)
    jira.forget_requests()

    refused = _publish(path, jira)
    refused_writes = _writes(jira)
    overwritten = _publish(path, jira, overwrite=True)

    assert (
        type(refused),
        [(edit.part.label, edit.edited_by) for edit in refused.edits] if isinstance(refused, Refused) else [],
        refused_writes,
        overwritten,
    ) == (
        Refused,
        [("planting", "Robin Editor")],
        [],
        Applied(("update   document: planting (blocks[2])",)),
    )


def test_a_title_edited_in_jira_while_skaldr_writes_the_description_stops_the_next_publish(
    tmp_path: Path,
) -> None:
    jira = FakeJira()
    path = write_garden_report(tmp_path, publish=_jira_publish(split=["tools"]))
    _publish(path, jira)
    write_garden_report(
        tmp_path, publish=_jira_publish(split=["tools"]), blocks=make_garden_blocks(planting="Sow in May.")
    )
    jira.edit_right_after_the_next_write("DEMO-1", summary="Garden guide")

    with pytest.raises(
        ConnectorError, match=r"^DEMO-1 was edited in Jira while skaldr wrote to it \(summary\)"
    ):
        _publish(path, jira)
    jira.forget_requests()
    again = _publish(path, jira)

    assert (
        type(again),
        [edit.part.label for edit in again.edits] if isinstance(again, Refused) else [],
        _writes(jira),
    ) == (Refused, ["title"], [])


def test_a_section_that_leaves_the_split_is_archived_by_closing_its_issue(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(tmp_path, publish=_jira_publish(split=["tools"]))
    _publish(path, jira)
    write_garden_report(tmp_path, publish=_jira_publish())
    jira.forget_requests()

    outcome = _publish(path, jira)

    assert (
        outcome.steps if isinstance(outcome, Applied) else (),
        jira.issues["DEMO-2"].fields["status"],
    ) == (
        ("update   document: page legend (badges), tools (blocks[1])", "archive  section tools (DEMO-2)"),
        DONE,
    )


def test_changing_the_site_of_a_target_is_a_move_that_writes_nothing(tmp_path: Path) -> None:
    jira = FakeJira()
    path = write_garden_report(tmp_path, publish=_jira_publish())
    _publish(path, jira)
    write_garden_report(tmp_path, publish=_jira_publish(where={**_jira_where(), "site": OTHER_SITE}))
    jira.forget_requests()

    with pytest.raises(
        PublishError,
        match=_exactly(
            f"the Jira target moved from {TARGET_LABEL} to {TARGET_LABEL} on {OTHER_SITE}; skaldr does not "
            "move pages or issues, so nothing was written. Publish once with the old target removed from the "
            "`publish` block, which archives the items skaldr created there and releases any page it wrote "
            "into, then add the new target and publish again"
        ),
    ):
        _publish(path, jira)
    assert _writes(jira) == []


def test_a_document_over_the_description_limit_stops_before_anything_is_sent(tmp_path: Path) -> None:
    jira = FakeJira()
    long_document: dict[str, Any] = {
        "publish": _jira_publish(),
        "blocks": [{"type": "text", "body": "x" * JIRA_DESCRIPTION_LIMIT}],
        "meta": {"title": "Garden handbook"},
    }
    path = write_garden_report(tmp_path, **long_document)
    parsed = parse_report(make_garden_report(**long_document))
    size = description_length("".join(JiraConnector().render_regions(parsed, lower_report(parsed))))

    with pytest.raises(
        PublishError,
        match=_exactly(
            f"{TARGET_LABEL}, document: the item has {size:,} characters of ADF, over the 32,767 a Jira item "
            "can take; split the document further with `split`, or shorten it"
        ),
    ):
        _publish(path, jira)
    assert jira.requests == []
