import re
from pathlib import Path
from typing import Any

import pytest

from skaldr.auth.store import SlackCredentials, save_slack
from skaldr.errors import AuthError, ConnectorError
from skaldr.export.lower import assemble_item_page, lower_regions, lowering_for
from skaldr.models import parse_report
from skaldr.publish import ConnectorRegistry, ContentLimit
from skaldr.publish.cli import installed_connectors, main
from skaldr.publish.slack.connector import SlackConnector
from skaldr.publish.slack.transport import SlackTransport
from skaldr.publish_block import JiraTarget, SlackTarget
from tests.factories import SLACK_CANVAS_ID, make_jira_target, make_slack_target
from tests.factories.auth_factory import make_slack_credentials
from tests.factories.publish_factory import make_garden_blocks, make_garden_report, write_garden_report
from tests.factories.slack_factory import InMemorySlack

DOCUMENT_CANVAS = "F000000001"
TOOLS_CANVAS = "F000000002"
DOCUMENT_STAMP = "Published with skaldr from document garden-handbook"
TOOLS_STAMP = "Published with skaldr from document garden-handbook, section tools"


def _connector(slack: InMemorySlack) -> SlackConnector:
    return SlackConnector(http=slack.mock(), sleep=lambda _: None)


def _registry(slack: InMemorySlack) -> ConnectorRegistry:
    return ConnectorRegistry([_connector(slack)])


def _slack_publish(**target: Any) -> dict[str, Any]:
    return {"doc_id": "garden-handbook", "targets": [make_slack_target(**target)]}


def _published(tmp_path: Path, slack: InMemorySlack, **target: Any) -> Path:
    save_slack(make_slack_credentials())
    path = write_garden_report(tmp_path, publish=_slack_publish(split=["tools"], **target))
    assert main(["publish", str(path), "--apply"], registry=_registry(slack)) == 0
    return path


def test_skaldr_has_a_slack_connector_installed() -> None:
    connector = installed_connectors().for_target(SlackTarget.model_validate(make_slack_target()))

    assert type(connector) is SlackConnector


def test_the_slack_connector_writes_sections_into_one_canvas_within_its_size_and_carries_no_look() -> None:
    connector = SlackConnector()

    assert (
        connector.target_type,
        connector.limits,
        connector.writes,
        connector.carries_look,
        connector.export_target,
    ) == (
        SlackTarget,
        (ContentLimit("item", 1_048_576, "characters of canvas Markdown"),),
        "section",
        False,
        "slack",
    )


@pytest.mark.parametrize(
    ("where", "existing"),
    [
        pytest.param({"canvas": SLACK_CANVAS_ID}, SLACK_CANVAS_ID, id="canvas"),
        pytest.param({"conversation": "C0EXAMPLE1"}, None, id="conversation"),
        pytest.param({}, None, id="nowhere"),
    ],
)
def test_a_canvas_target_names_the_canvas_it_writes_into(where: dict[str, str], existing: str | None) -> None:
    target = SlackTarget.model_validate(make_slack_target(where=where))

    assert SlackConnector().existing_item_id(target) == existing


def test_each_region_is_rendered_as_canvas_markdown() -> None:
    report = parse_report(make_garden_report(publish=_slack_publish()))
    lowering = lowering_for(report)
    page = assemble_item_page("Garden", list(lower_regions(lowering)), lowering, opens_the_document=True)

    assert SlackConnector().render_regions(report, page)[-1] == "## Planting\n\nSow in spring.\n"


def test_a_transport_signs_in_with_the_targets_workspace() -> None:
    asked: list[str | None] = []

    def sign_in(workspace: str | None) -> SlackCredentials:
        asked.append(workspace)
        return make_slack_credentials()

    target = SlackTarget.model_validate(make_slack_target(where={"workspace": "Example Garden"}))

    transport = SlackConnector(sign_in=sign_in).open_transport(target)

    assert (type(transport), asked) == (SlackTransport, ["Example Garden"])


def test_a_transport_without_a_sign_in_says_how_to_sign_in() -> None:
    target = SlackTarget.model_validate(make_slack_target())

    with pytest.raises(ConnectorError, match=r"^Not signed in to Slack; run `skaldr auth slack`$"):
        SlackConnector().open_transport(target)


def test_a_refused_sign_in_becomes_a_connector_error() -> None:
    def sign_in(_workspace: str | None) -> SlackCredentials:
        raise AuthError("the keychain is locked")

    with pytest.raises(ConnectorError, match=r"^the keychain is locked$"):
        SlackConnector(sign_in=sign_in).open_transport(SlackTarget.model_validate(make_slack_target()))


def test_a_target_of_another_service_is_refused() -> None:
    target = JiraTarget.model_validate(make_jira_target())
    refusal = "the Slack connector cannot publish to jira project PLAN under no parent issue"

    with pytest.raises(ConnectorError, match=f"^{re.escape(refusal)}$"):
        SlackConnector(sign_in=lambda _: make_slack_credentials()).open_transport(target)


def test_publishing_creates_the_document_and_its_split_canvas_links_both_and_publishing_again_sends_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slack = InMemorySlack()
    path = _published(tmp_path, slack)
    created = slack.writes()

    again = main(["publish", str(path), "--apply"], registry=_registry(slack))

    assert (again, created, slack.writes()[len(created) :], [channel for channel, _ in slack.messages]) == (
        0,
        [
            ("canvases.create", ""),
            ("chat.postMessage", ""),
            ("canvases.create", ""),
            ("chat.postMessage", ""),
        ],
        [],
        ["C0EXAMPLE1", "C0EXAMPLE1"],
    )
    assert capsys.readouterr().out.splitlines()[-1] == "Nothing to publish: every item matches the YAML."
    assert (
        slack.markdown_of(DOCUMENT_CANVAS).splitlines()[-1],
        slack.markdown_of(TOOLS_CANVAS).splitlines()[-1],
        slack.canvases[TOOLS_CANVAS].title,
    ) == (DOCUMENT_STAMP, TOOLS_STAMP, "Tools")


def test_a_changed_section_is_deleted_and_inserted_again(tmp_path: Path) -> None:
    slack = InMemorySlack()
    path = _published(tmp_path, slack)
    write_garden_report(
        tmp_path,
        publish=_slack_publish(split=["tools"]),
        blocks=make_garden_blocks(planting="Sow in late spring."),
    )
    slack.forget_requests()

    exit_code = main(["publish", str(path), "--apply"], registry=_registry(slack))

    assert (exit_code, slack.writes(), "Sow in late spring." in slack.markdown_of(DOCUMENT_CANVAS)) == (
        0,
        [("canvases.edit", "delete"), ("canvases.edit", "delete"), ("canvases.edit", "insert_after")],
        True,
    )


def test_an_edit_made_in_slack_stops_the_publish_until_it_is_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slack = InMemorySlack()
    path = _published(tmp_path, slack)
    slack.edit_by_hand(DOCUMENT_CANVAS, "Sow in spring.", "Sow in June.")
    capsys.readouterr()

    refused = main(["publish", str(path), "--apply"], registry=_registry(slack))
    refusal = capsys.readouterr()
    overwritten = main(["publish", str(path), "--apply", "--overwrite"], registry=_registry(slack))

    assert (refused, overwritten, "Sow in spring." in slack.markdown_of(DOCUMENT_CANVAS)) == (1, 0, True)
    assert "-Sow in spring.\n+Sow in June." in refusal.out


def test_naming_another_conversation_moves_no_canvas_and_posts_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slack = InMemorySlack()
    path = _published(tmp_path, slack)
    write_garden_report(
        tmp_path, publish=_slack_publish(split=["tools"], where={"conversation": "C0EXAMPLE2"})
    )
    slack.forget_requests()
    capsys.readouterr()

    exit_code = main(["publish", str(path), "--apply"], registry=_registry(slack))

    assert (exit_code, slack.writes(), capsys.readouterr().out.splitlines()[-1]) == (
        0,
        [],
        "Nothing to publish: every item matches the YAML.",
    )


def test_retiring_the_document_archives_each_canvas(tmp_path: Path) -> None:
    slack = InMemorySlack()
    path = _published(tmp_path, slack)
    write_garden_report(tmp_path, publish={"doc_id": "garden-handbook", "targets": []})

    exit_code = main(["publish", str(path), "--apply"], registry=_registry(slack))

    assert (exit_code, [(canvas.title, canvas.blocks) for canvas in slack.canvases.values()]) == (
        0,
        [
            (
                "Garden handbook (archived by skaldr)",
                ["skaldr archived this canvas: the document garden-handbook no longer publishes here."],
            ),
            (
                "Tools (archived by skaldr)",
                ["skaldr archived this canvas: the document garden-handbook no longer publishes here."],
            ),
        ],
    )


def test_publishing_into_a_named_canvas_writes_into_it_and_posts_no_link(tmp_path: Path) -> None:
    slack = InMemorySlack()
    canvas_id = slack.add_canvas("Blank canvas")
    save_slack(make_slack_credentials())
    path = write_garden_report(tmp_path, publish=_slack_publish(where={"canvas": canvas_id}))

    exit_code = main(["publish", str(path), "--apply"], registry=_registry(slack))

    assert (exit_code, slack.canvases[canvas_id].title, slack.messages, list(slack.canvases)) == (
        0,
        "Garden handbook",
        [],
        [canvas_id],
    )
    assert slack.markdown_of(canvas_id).splitlines()[-1] == DOCUMENT_STAMP


def test_publishing_without_a_slack_sign_in_stops_before_anything_is_sent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slack = InMemorySlack()
    path = write_garden_report(tmp_path, publish=_slack_publish())

    exit_code = main(["publish", str(path), "--apply"], registry=_registry(slack))

    assert (exit_code, capsys.readouterr().err, slack.requests) == (
        1,
        "error: Not signed in to Slack; run `skaldr auth slack`\n",
        [],
    )
