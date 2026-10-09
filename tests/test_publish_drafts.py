import re
from typing import Any

import pytest

from skaldr.errors import PublishError
from skaldr.models import Report, parse_report
from skaldr.publish import ContentLimit
from skaldr.publish.content import FIELDS, TITLE, ItemContent, section_part
from skaldr.publish.drafts import ItemDraft, draft_targets
from tests.factories import make_report, make_section
from tests.factories.publish_factory import (
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
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


def _document(sections: dict[str, str], fields_path: str = "publish.targets[0]") -> ItemDraft:
    return ItemDraft(
        None,
        ItemContent(title="Garden handbook", sections=sections),
        {
            TITLE: "meta.title",
            FIELDS: fields_path,
            **{section_part(key): path for key, path in _PATHS.items() if key in sections},
        },
    )


_PATHS = {
    "page header": "meta",
    "page legend": "badges",
    "blocks[0]": "blocks[0]",
    "tools": "blocks[1]",
    "planting": "blocks[2]",
}


def test_an_unsplit_target_is_one_item_holding_every_region_of_the_page() -> None:
    report = parse_garden_report(publish=make_notion_publish())

    (target,) = draft_targets(report, fake_registry(FakeTransport()))

    assert (target.label, target.document, target.sections) == (
        TARGET_LABEL,
        _document(
            {
                "page header": HEADER,
                "page legend": LEGEND,
                "blocks[0]": INTRO,
                "tools": TOOLS,
                "planting": PLANTING,
            }
        ),
        (),
    )


def test_a_split_parent_keeps_the_report_wide_contents_and_legend_and_the_child_holds_only_its_section() -> (
    None
):
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
                sections={
                    "page header": HEADER,
                    "page legend": LEGEND,
                    "blocks[0]": INTRO,
                    "planting": PLANTING,
                },
                fields={"Area": "Shed"},
            ),
            {
                TITLE: "meta.title",
                FIELDS: "publish.targets[0]",
                section_part("page header"): "meta",
                section_part("page legend"): "badges",
                section_part("blocks[0]"): "blocks[0]",
                section_part("planting"): "blocks[2]",
            },
        ),
        (
            ItemDraft(
                "tools",
                ItemContent(
                    title="Tools", sections={"tools": TOOLS}, fields={"Area": "Tool wall", "Owner": "Rowan"}
                ),
                {TITLE: "blocks[1].title", FIELDS: "publish.targets[0]", section_part("tools"): "blocks[1]"},
            ),
        ),
    )


def test_a_target_built_from_some_sections_leaves_the_other_blocks_out() -> None:
    report = parse_garden_report(publish=make_notion_publish(**{"from": ["planting"]}))

    (target,) = draft_targets(report, fake_registry(FakeTransport()))

    assert target.document.content.sections == {
        "page header": 'For new members {color="gray"}\n<table_of_contents/>\n',
        "page legend": LEGEND,
        "planting": PLANTING,
    }


def test_a_top_level_block_that_is_not_a_section_is_keyed_by_its_place() -> None:
    blocks = [*make_garden_blocks(), {"type": "text", "body": "Questions go to the noticeboard."}]
    report = parse_garden_report(publish=make_notion_publish(split=["tools", "planting"]), blocks=blocks)

    (target,) = draft_targets(report, fake_registry(FakeTransport()))

    assert list(target.document.content.sections) == ["page header", "page legend", "blocks[0]", "blocks[3]"]


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
        f"{TARGET_LABEL}, section tools: section tools (blocks[1]) has 39 characters, over the 25 a notion "
        "section can take; split the document further with `split`, or shorten it"
    )

    with pytest.raises(PublishError, match=f"^{re.escape(expected)}$"):
        draft_targets(_plain_garden_report(split=["tools"]), registry)


def test_an_item_over_a_connector_limit_fails_naming_the_item_and_the_limit() -> None:
    registry = fake_registry(FakeTransport(), (ContentLimit("item", 60, "characters"),))
    expected = (
        f"{TARGET_LABEL}, document: the item has 62 characters, over the 60 a notion item can take; "
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
        "blocks[0]": "Welcome to the garden.\n",
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
