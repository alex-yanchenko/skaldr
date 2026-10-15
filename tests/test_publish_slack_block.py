import re
from typing import Any

import pytest

from skaldr.errors import ReportError
from skaldr.models import parse_report
from skaldr.publish_block import Publish, slack_canvas_id, slack_conversation_id
from tests.factories import (
    SLACK_CANVAS_ID,
    SLACK_CONVERSATION_ID,
    SLACK_TEAM_ID,
    make_notion_target,
    make_publish_report,
    make_slack_target,
)

OTHER_CONVERSATION_ID = "D0EXAMPLE2"
CANVAS_LINK = f"https://example.slack.com/docs/{SLACK_TEAM_ID}/{SLACK_CANVAS_ID}"
CHANNEL_LINK = f"https://example.slack.com/archives/{SLACK_CONVERSATION_ID}"


def _parse(publish: dict[str, Any]) -> Publish:
    parsed = parse_report(make_publish_report(publish)).publish
    assert parsed is not None
    return parsed


def _rejects(publish: dict[str, Any], message: str) -> None:
    with pytest.raises(ReportError, match=re.escape(message)):
        _parse(publish)


def test_a_slack_target_reads_every_key() -> None:
    target = make_slack_target(
        where={"conversation": SLACK_CONVERSATION_ID, "workspace": "Example Garden"},
        split=["st1"],
    )

    publish = _parse({"doc_id": "plan", "targets": [target]})

    assert publish.model_dump(mode="json")["targets"] == [
        {
            "to": "slack",
            "where": {"conversation": SLACK_CONVERSATION_ID, "canvas": None, "workspace": "Example Garden"},
            "from": None,
            "split": ["st1"],
            "overrides": {},
        }
    ]


def test_a_slack_target_without_where_publishes_canvases_it_links_nowhere() -> None:
    publish = _parse({"doc_id": "plan", "targets": [{"to": "slack"}]})

    target = publish.targets[0]
    assert (
        target.model_dump(mode="json")["where"],
        target.place_key(),
        target.location_label(),
    ) == (
        {"conversation": None, "canvas": None, "workspace": None},
        ("slack", "", ""),
        "slack without a conversation",
    )


@pytest.mark.parametrize(
    ("where", "place_key", "label"),
    [
        pytest.param(
            {"conversation": SLACK_CONVERSATION_ID},
            ("slack", SLACK_CONVERSATION_ID, ""),
            f"slack conversation {SLACK_CONVERSATION_ID}",
            id="conversation",
        ),
        pytest.param(
            {"conversation": CHANNEL_LINK, "workspace": "Example Garden"},
            ("slack", SLACK_CONVERSATION_ID, ""),
            f"slack conversation {SLACK_CONVERSATION_ID}",
            id="conversation-link-and-a-workspace-outside-the-place",
        ),
        pytest.param(
            {"canvas": CANVAS_LINK},
            ("slack", "", SLACK_CANVAS_ID),
            f"slack canvas {SLACK_CANVAS_ID} (written into)",
            id="canvas-written-into",
        ),
    ],
)
def test_a_slack_target_is_placed_by_its_conversation_or_its_canvas(
    where: dict[str, Any], place_key: tuple[str, ...], label: str
) -> None:
    target = _parse({"doc_id": "plan", "targets": [make_slack_target(where=where)]}).targets[0]

    assert (target.place_key(), target.location_label()) == (place_key, label)


@pytest.mark.parametrize(
    ("reference", "conversation_id"),
    [
        pytest.param(SLACK_CONVERSATION_ID, SLACK_CONVERSATION_ID, id="channel-id"),
        pytest.param("G0EXAMPLE3", "G0EXAMPLE3", id="private-channel-id"),
        pytest.param(OTHER_CONVERSATION_ID, OTHER_CONVERSATION_ID, id="dm-id"),
        pytest.param(f"  {SLACK_CONVERSATION_ID}\n", SLACK_CONVERSATION_ID, id="surrounding-whitespace"),
        pytest.param(CHANNEL_LINK, SLACK_CONVERSATION_ID, id="archives-link"),
        pytest.param(f"{CHANNEL_LINK}/p1791921965893669", SLACK_CONVERSATION_ID, id="message-link"),
        pytest.param(
            f"https://app.slack.com/client/{SLACK_TEAM_ID}/{SLACK_CONVERSATION_ID}",
            SLACK_CONVERSATION_ID,
            id="app-link",
        ),
        pytest.param("c0example1", None, id="lowercase"),
        pytest.param("U0EXAMPLE1", None, id="user-id"),
        pytest.param("#garden", None, id="channel-name"),
        pytest.param(f"https://example.com/archives/{SLACK_CONVERSATION_ID}", None, id="other-host"),
        pytest.param(f"https://slack.com.example.com/archives/{SLACK_CONVERSATION_ID}", None, id="lookalike"),
        pytest.param(f"ftp://example.slack.com/archives/{SLACK_CONVERSATION_ID}", None, id="ftp"),
    ],
)
def test_a_conversation_id_comes_from_an_id_or_a_slack_link(
    reference: str, conversation_id: str | None
) -> None:
    assert slack_conversation_id(reference) == conversation_id


@pytest.mark.parametrize(
    ("reference", "canvas_id"),
    [
        pytest.param(SLACK_CANVAS_ID, SLACK_CANVAS_ID, id="canvas-id"),
        pytest.param(CANVAS_LINK, SLACK_CANVAS_ID, id="canvas-link"),
        pytest.param(f"{CANVAS_LINK}?focus_section_id=temp:C:X", SLACK_CANVAS_ID, id="link-with-a-query"),
        pytest.param(SLACK_CONVERSATION_ID, None, id="channel-id"),
        pytest.param(f"https://example.com/docs/{SLACK_TEAM_ID}/{SLACK_CANVAS_ID}", None, id="other-host"),
        pytest.param("", None, id="empty"),
    ],
)
def test_a_canvas_id_comes_from_an_id_or_a_canvas_link(reference: str, canvas_id: str | None) -> None:
    assert slack_canvas_id(reference) == canvas_id


@pytest.mark.parametrize(
    ("target", "message"),
    [
        pytest.param(
            make_slack_target(where={"conversation": SLACK_CONVERSATION_ID, "canvas": SLACK_CANVAS_ID}),
            "a slack target names at most one of `conversation` or `canvas`",
            id="both",
        ),
        pytest.param(
            make_slack_target(where={"conversation": "#garden"}),
            "'#garden' is not a Slack channel or DM id (C..., G... or D...) or a link to one",
            id="channel-name",
        ),
        pytest.param(
            make_slack_target(where={"canvas": "garden handbook"}),
            "'garden handbook' is not a Slack canvas id (F...) or a link to one",
            id="canvas-title",
        ),
        pytest.param(
            make_slack_target(split=["st1"], overrides={"st1": {"fields": {"Area": "Shed"}}}),
            "a slack target sets no fields: a canvas holds a title and content only, so leave out "
            "`overrides.st1.fields`",
            id="override-fields",
        ),
        pytest.param(
            make_slack_target(where={"fields": {"Area": "Shed"}}),
            "publish.targets.0.slack.where.fields: Extra inputs are not permitted",
            id="where-fields",
        ),
        pytest.param(
            {"to": "confluence", "where": {}},
            "does not match any of the expected tags: 'notion', 'jira', 'slack'",
            id="unknown-service",
        ),
    ],
)
def test_a_slack_target_checks_its_keys(target: dict[str, Any], message: str) -> None:
    _rejects({"doc_id": "plan", "targets": [target]}, message)


def test_an_empty_override_is_accepted() -> None:
    target = make_slack_target(split=["st1"], overrides={"st1": {}})

    publish = _parse({"doc_id": "plan", "targets": [target]})

    assert publish.targets[0].fields_for("st1") == {}


@pytest.mark.parametrize(
    ("targets", "message"),
    [
        pytest.param(
            [
                make_slack_target(),
                make_slack_target(where={"conversation": CHANNEL_LINK, "workspace": "Example Garden"}),
            ],
            f"publish targets 1 and 2 both write to slack conversation {SLACK_CONVERSATION_ID}",
            id="one-conversation-named-two-ways",
        ),
        pytest.param(
            [{"to": "slack"}, make_slack_target(where={})],
            "publish targets 1 and 2 both write to slack without a conversation",
            id="two-unlinked",
        ),
    ],
)
def test_two_slack_targets_cannot_write_to_one_place(targets: list[dict[str, Any]], message: str) -> None:
    _rejects({"doc_id": "plan", "targets": targets}, message)


def test_a_slack_target_sits_beside_a_notion_target() -> None:
    publish = _parse(
        {
            "doc_id": "plan",
            "targets": [
                make_notion_target(),
                make_slack_target(),
                make_slack_target(where={"conversation": OTHER_CONVERSATION_ID}),
            ],
        }
    )

    assert [target.service() for target in publish.targets] == ["notion", "slack", "slack"]
