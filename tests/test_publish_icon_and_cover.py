from pathlib import Path
from typing import Any

from skaldr.publish.content import COVER, ICON, TITLE, ItemContent, section_part
from skaldr.publish.drafts import draft_targets, load_authored
from skaldr.publish.engine import (
    Applied,
    ApplyOutcome,
    ItemStatus,
    PublishDiff,
    Refused,
    RemoteEdit,
    YamlChange,
    apply_publish,
    diff_publish,
    prepare_publish,
    publish_status,
)
from skaldr.publish.plan import ItemRef
from tests.factories.publish_factory import (
    TARGET_LABEL,
    FakeTransport,
    fake_registry,
    make_garden_blocks,
    make_garden_meta,
    make_notion_publish,
    write_garden_report,
)
from tests.factories.report_factory import NOTION_PAGE_ID

DOCUMENT = ItemRef(TARGET_LABEL, None)
TOOLS = ItemRef(TARGET_LABEL, "tools")
PLANTING = ItemRef(TARGET_LABEL, "planting")
SEEDLING = "🌱"
SUNFLOWER = "🌻"
FIRE = "🔥"
COVER_URL = "https://example.com/garden.png"
SPRING = "## Planting\nSow in spring.\n"
TOOLS_TEXT = '## Tools\n<span color="blue">**api**</span>\n- Spade.\n'
LEGEND_TEXT = (
    "<details>\n"
    "<summary>Legend: badges used on this page</summary>\n"
    '\t- <span color="blue">**api**</span> the API\n'
    "</details>\n"
)


def _look(**look: str) -> dict[str, Any]:
    return {"meta": make_garden_meta(**look)}


def _publish(path: Path, transport: FakeTransport, *, overwrite: bool = False) -> ApplyOutcome:
    return apply_publish(prepare_publish(path, fake_registry(transport)), overwrite=overwrite)


def _drafted(path: Path, section_id: str | None = None) -> ItemContent:
    (target,) = draft_targets(load_authored(path), fake_registry(FakeTransport()))
    return next(item.content for item in target.items if item.section_id == section_id)


def _published_then_rewritten(
    tmp_path: Path, transport: FakeTransport, published: dict[str, Any], rewritten: dict[str, Any]
) -> Path:
    path = write_garden_report(tmp_path, **published)
    _publish(path, transport)
    write_garden_report(tmp_path, **rewritten)
    transport.forget_calls()
    return path


def _looks(transport: FakeTransport) -> list[tuple[str | None, str | None]]:
    return [(item.icon, item.cover) for item in transport.items.values()]


def test_a_first_publish_sets_the_icon_on_every_item_and_the_cover_on_the_document(tmp_path: Path) -> None:
    path = write_garden_report(tmp_path, **_look(icon=SEEDLING, cover=COVER_URL))
    transport = FakeTransport()

    _publish(path, transport)

    assert (_looks(transport), transport.items["page-1"].content, transport.items["page-2"].content) == (
        [(SEEDLING, COVER_URL), (SEEDLING, None)],
        _drafted(path),
        _drafted(path, "tools"),
    )


def test_a_connector_that_carries_no_icon_or_cover_never_plans_or_sends_them(tmp_path: Path) -> None:
    transport = FakeTransport()
    registry = fake_registry(transport, carries_look=False)
    path = write_garden_report(tmp_path, **_look(icon=SEEDLING, cover=COVER_URL))
    first = apply_publish(prepare_publish(path, registry))
    write_garden_report(tmp_path, **_look(icon=SUNFLOWER))
    transport.forget_calls()

    again = apply_publish(prepare_publish(path, registry))

    assert (first, again, transport.writes(), _looks(transport)) == (
        Applied(('create   document "Garden handbook"', 'create   section tools "Tools"')),
        Applied(()),
        [],
        [(None, None), (None, None)],
    )


def test_a_changed_icon_and_a_removed_cover_are_written_to_each_item_that_shows_them(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(
        tmp_path, transport, _look(icon=SEEDLING, cover=COVER_URL), _look(icon=SUNFLOWER)
    )

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), _looks(transport)) == (
        Applied(("update   document: icon, cover", "update   section tools: icon")),
        [
            ("write_fields", "page-1", f"icon {SUNFLOWER}", "cover None"),
            ("write_fields", "page-2", f"icon {SUNFLOWER}"),
        ],
        [(SUNFLOWER, None), (SUNFLOWER, None)],
    )


def test_an_icon_removed_from_the_yaml_is_cleared(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, _look(icon=SEEDLING), _look())

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), _looks(transport)) == (
        Applied(("update   document: icon", "update   section tools: icon")),
        [("write_fields", "page-1", "icon None"), ("write_fields", "page-2", "icon None")],
        [(None, None), (None, None)],
    )


def test_an_icon_a_person_changes_stops_the_publish_and_overwrite_puts_the_yaml_icon_back(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, _look(icon=SEEDLING), _look(icon=SEEDLING))
    transport.set_icon_by_hand("page-1", FIRE)

    refused = _publish(path, transport)
    refused_writes = transport.writes()
    overwritten = _publish(path, transport, overwrite=True)

    assert (refused, refused_writes, overwritten, transport.writes(), _looks(transport)) == (
        Refused(
            (RemoteEdit(DOCUMENT, ICON, "meta.icon", f"{SEEDLING}\n", f"{FIRE}\n", None, None),), "edited"
        ),
        [],
        Applied(("update   document: icon",)),
        [("write_fields", "page-1", f"icon {SEEDLING}")],
        [(SEEDLING, None), (SEEDLING, None)],
    )


def test_a_cover_a_person_removes_is_a_remote_edit(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, _look(cover=COVER_URL), _look(cover=COVER_URL))
    transport.set_cover_by_hand("page-1", None)

    assert publish_status(prepare_publish(path, fake_registry(transport))) == (
        ItemStatus(DOCUMENT, "page-1", ("edited remotely",)),
        ItemStatus(TOOLS, "page-2", ("in sync",)),
    )


def test_an_icon_and_cover_a_person_sets_where_the_yaml_sets_none_are_left_alone(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {}, {})
    transport.set_icon_by_hand("page-1", FIRE)
    transport.set_cover_by_hand("page-1", COVER_URL)

    statuses = publish_status(prepare_publish(path, fake_registry(transport)))
    outcome = _publish(path, transport)

    assert (statuses, outcome, transport.writes(), _looks(transport)) == (
        (ItemStatus(DOCUMENT, "page-1", ("in sync",)), ItemStatus(TOOLS, "page-2", ("in sync",))),
        Applied(()),
        [],
        [(FIRE, COVER_URL), (None, None)],
    )


def test_an_icon_the_yaml_adds_replaces_one_a_person_set_without_a_remote_edit(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(tmp_path, transport, {}, _look(icon=SEEDLING))
    transport.set_icon_by_hand("page-1", FIRE)

    outcome = _publish(path, transport)

    assert (outcome, transport.writes(), _looks(transport)) == (
        Applied(("update   document: icon", "update   section tools: icon")),
        [("write_fields", "page-1", f"icon {SEEDLING}"), ("write_fields", "page-2", f"icon {SEEDLING}")],
        [(SEEDLING, None), (SEEDLING, None)],
    )


def test_writing_into_a_page_sets_the_yaml_icon_and_keeps_a_cover_the_yaml_does_not_set(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    transport.seed(NOTION_PAGE_ID, "Blank page", None)
    transport.items[NOTION_PAGE_ID].icon = FIRE
    transport.items[NOTION_PAGE_ID].cover = COVER_URL
    path = write_garden_report(
        tmp_path, publish=make_notion_publish(where={"page": NOTION_PAGE_ID}), **_look(icon=SEEDLING)
    )

    _publish(path, transport)
    transport.forget_calls()

    assert (_looks(transport), _publish(path, transport), transport.writes()) == (
        [(SEEDLING, COVER_URL)],
        Applied(()),
        [],
    )


def test_the_diff_shows_a_changed_icon_and_cover_with_their_yaml_locations(tmp_path: Path) -> None:
    transport = FakeTransport()
    path = _published_then_rewritten(
        tmp_path, transport, _look(icon=SEEDLING), _look(icon=SUNFLOWER, cover=COVER_URL)
    )

    diff = diff_publish(prepare_publish(path, fake_registry(transport)))

    assert diff == PublishDiff(
        (),
        (
            YamlChange(DOCUMENT, ICON, "meta.icon", f"{SEEDLING}\n", f"{SUNFLOWER}\n"),
            YamlChange(DOCUMENT, COVER, "meta.cover", None, f"{COVER_URL}\n"),
            YamlChange(TOOLS, ICON, "meta.icon", f"{SEEDLING}\n", f"{SUNFLOWER}\n"),
        ),
    )


def test_the_diff_lists_the_icon_of_an_item_never_published_and_of_an_item_removed(tmp_path: Path) -> None:
    transport = FakeTransport()
    without_tools = [block for block in make_garden_blocks() if block.get("id") != "tools"]
    path = _published_then_rewritten(
        tmp_path,
        transport,
        _look(icon=SEEDLING),
        {**_look(icon=SEEDLING), "publish": make_notion_publish(split=["planting"]), "blocks": without_tools},
    )

    diff = diff_publish(prepare_publish(path, fake_registry(transport)))

    assert diff == PublishDiff(
        (),
        (
            YamlChange(DOCUMENT, section_part("planting"), None, SPRING, None),
            YamlChange(PLANTING, TITLE, "blocks[1].title", None, "Planting\n"),
            YamlChange(PLANTING, ICON, "meta.icon", None, f"{SEEDLING}\n"),
            YamlChange(PLANTING, section_part("planting"), "blocks[1]", None, SPRING),
            YamlChange(TOOLS, TITLE, None, "Tools\n", None),
            YamlChange(TOOLS, ICON, None, f"{SEEDLING}\n", None),
            YamlChange(TOOLS, section_part("page legend"), None, LEGEND_TEXT, None),
            YamlChange(TOOLS, section_part("tools"), None, TOOLS_TEXT, None),
        ),
    )
