import re
from typing import Any

import pytest

from skaldr.errors import PublishError
from skaldr.models import Report, parse_report
from skaldr.publish import ContentLimit
from skaldr.publish.content import FIELDS, TITLE, ItemContent, section_part
from skaldr.publish.drafts import ItemDraft, draft_targets
from tests.factories import make_report, make_section, make_table
from tests.factories.publish_factory import (
    INTRO_KEY,
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_notion_publish,
    parse_garden_report,
)

HEADER = 'For new members {color="gray"}\n<table_of_contents/>\n'
LEGEND = (
    "<details>\n"
    "<summary>Legend: badges used on this page</summary>\n"
    '\t- <span color="blue">**api**</span> the API\n'
    "</details>\n"
)
INTRO = "Welcome to the garden.\n"
TOOLS = '## Tools\n<span color="blue">**api**</span>\n- Spade.\n'
LONG_ITEM = "A spade, a fork and a rake."
PLANTING = "## Planting\nSow in spring.\n"
WHERE_FIELDS = "publish.targets[0].where.fields"


def test_an_unsplit_target_is_one_item_holding_every_region_of_the_page() -> None:
    report = parse_garden_report(publish=make_notion_publish())

    (target,) = draft_targets(report, fake_registry(FakeTransport()))

    assert (target.label, target.document, target.sections) == (
        TARGET_LABEL,
        ItemDraft(
            None,
            ItemContent(
                title="Garden handbook",
                sections={
                    "page header": HEADER,
                    "page legend": LEGEND,
                    INTRO_KEY: INTRO,
                    "tools": TOOLS,
                    "planting": PLANTING,
                },
            ),
            {
                TITLE: "meta.title",
                FIELDS: WHERE_FIELDS,
                section_part("page header"): "meta",
                section_part("page legend"): "badges",
                section_part(INTRO_KEY): "blocks[0]",
                section_part("tools"): "blocks[1]",
                section_part("planting"): "blocks[2]",
            },
        ),
        (),
    )


def test_a_split_parent_keeps_the_contents_and_each_item_lists_only_the_badges_it_uses() -> None:
    report = parse_garden_report(
        publish=make_notion_publish(
            split=["tools"],
            where={"parent_page": "0123456789abcdef0123456789abcdef", "fields": {"Area": "Shed"}},
            overrides={"tools": {"fields": {"Area": "Tool wall", "Owner": "Rowan"}}},
        )
    )

    (target,) = draft_targets(report, fake_registry(FakeTransport()))

    assert (target.document, target.sections) == (
        ItemDraft(
            None,
            ItemContent(
                title="Garden handbook",
                sections={"page header": HEADER, INTRO_KEY: INTRO, "planting": PLANTING},
                fields={"Area": "Shed"},
            ),
            {
                TITLE: "meta.title",
                FIELDS: WHERE_FIELDS,
                section_part("page header"): "meta",
                section_part(INTRO_KEY): "blocks[0]",
                section_part("planting"): "blocks[2]",
            },
        ),
        (
            ItemDraft(
                "tools",
                ItemContent(
                    title="Tools",
                    sections={"page legend": LEGEND, "tools": TOOLS},
                    fields={"Area": "Tool wall", "Owner": "Rowan"},
                ),
                {
                    TITLE: "blocks[1].title",
                    FIELDS: "publish.targets[0].overrides.tools.fields",
                    section_part("page legend"): "badges",
                    section_part("tools"): "blocks[1]",
                },
            ),
        ),
    )


def test_a_split_section_without_overrides_takes_its_fields_from_where() -> None:
    report = parse_garden_report(
        publish=make_notion_publish(
            split=["tools"],
            where={"parent_page": "0123456789abcdef0123456789abcdef", "fields": {"Area": "Shed"}},
        )
    )

    (target,) = draft_targets(report, fake_registry(FakeTransport()))

    assert (target.sections[0].content.fields, target.sections[0].paths[FIELDS]) == (
        {"Area": "Shed"},
        WHERE_FIELDS,
    )


def test_an_item_puts_its_legend_right_before_its_own_first_top_level_table() -> None:
    blocks = [
        make_section("tools", title="Tools", collapsed=False),
        {"type": "badge_row", "items": [{"key": "API"}]},
        make_table([{"key": "a", "label": "A"}], rows=[{"a": "x"}]),
    ]
    report = parse_garden_report(publish=make_notion_publish(split=["tools"]), blocks=blocks)

    (target,) = draft_targets(report, fake_registry(FakeTransport()))

    assert (list(target.document.content.sections), list(target.sections[0].content.sections)) == (
        ["page header", "block e139b771", "page legend", "block 9229c315"],
        ["tools"],
    )


def test_a_target_built_from_some_sections_leaves_the_other_blocks_out() -> None:
    report = parse_garden_report(publish=make_notion_publish(**{"from": ["planting"]}))

    (target,) = draft_targets(report, fake_registry(FakeTransport()))

    assert target.document.content.sections == {"page header": HEADER, "planting": PLANTING}


def test_a_heading_is_keyed_by_its_anchor_and_other_blocks_by_their_content() -> None:
    blocks = [
        {"type": "heading", "text": "Daily jobs"},
        {"type": "text", "body": "Water daily."},
        {"type": "text", "body": "Water daily."},
        {"type": "text", "body": "Weed weekly."},
    ]
    report = parse_garden_report(publish=make_notion_publish(), blocks=blocks)

    (target,) = draft_targets(report, fake_registry(FakeTransport()))

    assert list(target.document.content.sections) == [
        "page header",
        "daily-jobs",
        "block 355f322b",
        "block 355f322b #2",
        "block c6216b93",
    ]


def _plain_garden_report(**target: Any) -> Report:
    blocks = [
        {"type": "text", "body": "Welcome to the garden."},
        make_section(
            "tools", title="Tools", collapsed=False, blocks=[{"type": "list", "items": [LONG_ITEM]}]
        ),
    ]
    return parse_report(
        make_report(meta={"title": "Garden handbook"}, publish=make_notion_publish(**target), blocks=blocks)
    )


def test_a_section_over_a_connector_limit_fails_naming_the_section_and_the_limit() -> None:
    registry = fake_registry(FakeTransport(), (ContentLimit("section", 25, "characters"),))
    expected = (
        f"{TARGET_LABEL}, section tools: section tools (blocks[1]) has 39 characters, over the 25 a Notion "
        "section can take; split the document further with `split`, or shorten it"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        draft_targets(_plain_garden_report(split=["tools"]), registry)


def test_an_item_over_a_connector_limit_fails_naming_the_item_and_the_limit() -> None:
    registry = fake_registry(FakeTransport(), (ContentLimit("item", 60, "characters"),))
    expected = (
        f"{TARGET_LABEL}, document: the item has 62 characters, over the 60 a Notion item can take; "
        "split the document further with `split`, or shorten it"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        draft_targets(_plain_garden_report(), registry)


def test_content_at_a_connector_limit_fits() -> None:
    registry = fake_registry(
        FakeTransport(), (ContentLimit("item", 62, "characters"), ContentLimit("section", 39, "characters"))
    )

    (target,) = draft_targets(_plain_garden_report(), registry)

    assert target.document.content.sections == {
        INTRO_KEY: "Welcome to the garden.\n",
        "tools": f"## Tools\n- {LONG_ITEM}\n",
    }


def test_a_report_without_a_publish_block_is_refused() -> None:
    expected = (
        "the document has no `publish` block, so it has nowhere to publish; add one (see `skaldr --guide`)"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        draft_targets(parse_report(make_report()), fake_registry(FakeTransport()))


def test_each_draft_carries_the_target_the_publish_block_names() -> None:
    report = parse_garden_report()

    (target,) = draft_targets(report, fake_registry(FakeTransport()))

    assert report.publish is not None
    assert target.target is report.publish.targets[0]
