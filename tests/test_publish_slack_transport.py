import hashlib
import re

import pytest

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.content import TITLE, ItemContent, section_part
from skaldr.publish.slack.canvas_markdown import UNKEYED_SECTION, archived_line
from skaldr.publish.transport import (
    AddSection,
    ContentWrite,
    FieldsWrite,
    ItemLink,
    LinksWrite,
    NewItem,
    Release,
    RemoteItem,
    RemoveSection,
    ReplaceSection,
    SectionRequest,
    ShownLink,
    Stamp,
)
from skaldr.publish_block import SlackTarget
from skaldr.publish_block.target import JsonFields
from tests.factories import make_slack_target
from tests.factories.slack_factory import InMemorySlack

TITLE_TEXT = "Garden handbook"
STAMP = Stamp("garden-handbook", None)
STAMP_LINE = "Published with skaldr from document garden-handbook"
CONTENT = ItemContent(
    title=TITLE_TEXT,
    sections={
        "intro": "Welcome to the garden.\n",
        "tools": "## Tools\n\n- Spade.\n- Rake.\n",
        "planting": "## Planting\n\nSow in spring.\n",
    },
)
LINKED = SlackTarget.model_validate(make_slack_target())
UNLINKED = SlackTarget.model_validate({"to": "slack"})
CANVAS = "F000000001"
CANVAS_LINK = f"https://example-garden.slack.com/docs/T0EXAMPLE1/{CANVAS}"
STORED = (
    f"# {TITLE_TEXT}\n\n"
    "Welcome to the garden.\n\n"
    "## Tools\n\n"
    "* Spade.\n* Rake.\n\n"
    "## Planting\n\n"
    "Sow in spring.\n\n"
    f"{STAMP_LINE}\n"
)
COMPARABLE_SECTIONS = {
    "intro": "Welcome to the garden.\n",
    "tools": "## Tools\n\n* Spade.\n* Rake.\n",
    "planting": "## Planting\n\nSow in spring.\n",
}
DEMO_12 = ShownLink(
    service="jira", item_id="DEMO-12", url="https://example.atlassian.net/browse/DEMO-12", title="DEMO-12"
)


def _section(canvas_id: str, generation: int, index: int) -> str:
    return f"temp:C:{canvas_id}-{generation}-{index}"


def _created(slack: InMemorySlack, target: SlackTarget = UNLINKED) -> RemoteItem:
    created = slack.transport().create_item(NewItem(target, STAMP, CONTENT))
    slack.forget_requests()
    return created


def _removing_tools(raw: dict[str, str]) -> SectionRequest:
    return SectionRequest(RemoveSection("tools", raw["tools"]), raw, STAMP)


def _edits(slack: InMemorySlack) -> list[dict[str, object]]:
    return [form["changes"][0] for method, form in slack.requests if method == "canvases.edit"]


def _digest(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def test_a_new_canvas_holds_the_content_and_the_stamp_and_its_link_is_posted_once() -> None:
    slack = InMemorySlack()

    created = slack.transport().create_item(NewItem(LINKED, STAMP, CONTENT))

    assert (created, slack.requests[0], slack.messages, slack.markdown_of(CANVAS)) == (
        RemoteItem(
            CANVAS,
            ItemContent(title=TITLE_TEXT, sections=COMPARABLE_SECTIONS),
            COMPARABLE_SECTIONS,
            STAMP,
            marker=_digest(STORED),
            links=(),
        ),
        (
            "canvases.create",
            {
                "title": TITLE_TEXT,
                "document_content": {
                    "type": "markdown",
                    "markdown": "Welcome to the garden.\n\n## Tools\n\n- Spade.\n- Rake.\n\n## Planting\n\n"
                    f"Sow in spring.\n\n{STAMP_LINE}\n",
                },
            },
        ),
        [("C0EXAMPLE1", f"{TITLE_TEXT}: {CANVAS_LINK}")],
        STORED,
    )


def test_a_canvas_with_no_conversation_is_posted_nowhere() -> None:
    slack = InMemorySlack()

    slack.transport().create_item(NewItem(UNLINKED, STAMP, CONTENT))

    assert (slack.messages, slack.calls()) == ([], ["canvases.create", "canvases.getContent markdown"])


def test_a_canvas_whose_link_cannot_be_posted_is_named_so_the_next_run_can_find_it() -> None:
    slack = InMemorySlack()
    slack.fail_next("chat.postMessage", "channel_not_found")

    with pytest.raises(ConnectorError) as raised:
        slack.transport().create_item(NewItem(LINKED, STAMP, CONTENT))

    assert (type(raised.value), str(raised.value), list(slack.canvases)) == (
        ConnectorError,
        f'skaldr wrote Slack canvas {CANVAS} for "{TITLE_TEXT}" but could not finish writing it: Slack '
        "refused to post the canvas link in C0EXAMPLE1 (channel_not_found)",
        [CANVAS],
    )


def test_a_canvas_slack_refuses_to_create_leaves_nothing_behind() -> None:
    slack = InMemorySlack()
    slack.fail_next("canvases.create", "canvas_creation_failed")

    with pytest.raises(WriteRejectedError) as raised:
        slack.transport().create_item(NewItem(LINKED, STAMP, CONTENT))

    assert (str(raised.value), slack.canvases, slack.messages) == (
        "Slack refused to create a canvas (canvas_creation_failed)",
        {},
        [],
    )


def test_a_read_keys_the_canvas_by_section_and_marks_it_with_a_digest_of_its_markdown() -> None:
    slack = InMemorySlack()
    _created(slack)

    read = slack.transport().read_item(CANVAS, CONTENT)

    assert read == RemoteItem(
        CANVAS,
        ItemContent(title=TITLE_TEXT, sections=COMPARABLE_SECTIONS),
        COMPARABLE_SECTIONS,
        STAMP,
        marker=_digest(STORED),
        links=(),
    )


@pytest.mark.parametrize(
    ("item_id", "message"),
    [
        pytest.param("no-such-item", "'no-such-item' is not a Slack canvas id", id="not-an-id"),
        pytest.param(
            "F999999999",
            "Slack could not read canvas F999999999: the canvas is gone or this sign-in cannot see it "
            "(canvas_not_found)",
            id="gone",
        ),
    ],
)
def test_a_canvas_slack_does_not_have_is_not_found(item_id: str, message: str) -> None:
    with pytest.raises(ItemNotFoundError, match=f"^{re.escape(message)}$"):
        InMemorySlack().transport().read_item(item_id, CONTENT)


def test_a_section_is_replaced_by_deleting_its_blocks_and_inserting_its_new_text_with_fresh_ids() -> None:
    slack = InMemorySlack()
    created = _created(slack)
    raw = dict(created.raw_sections)
    change = ReplaceSection("planting", raw["planting"], "## Planting\n\nSow in May.\n", "tools")

    written = slack.transport().write_section(CANVAS, SectionRequest(change, raw, STAMP))

    assert (slack.calls(), _edits(slack), slack.markdown_of(CANVAS), dict(written.raw_sections)) == (
        [
            "canvases.getContent markdown",
            "canvases.getContent html",
            "canvases.edit",
            "canvases.getContent html",
            "canvases.edit",
            "canvases.getContent html",
            "canvases.edit",
            "canvases.getContent markdown",
        ],
        [
            {"operation": "delete", "section_id": _section(CANVAS, 0, 5)},
            {"operation": "delete", "section_id": _section(CANVAS, 1, 4)},
            {
                "operation": "insert_after",
                "section_id": _section(CANVAS, 2, 3),
                "document_content": {"type": "markdown", "markdown": "## Planting\n\nSow in May.\n"},
            },
        ],
        STORED.replace("Sow in spring.", "Sow in May."),
        {**COMPARABLE_SECTIONS, "planting": "## Planting\n\nSow in May.\n"},
    )


def test_a_section_added_first_goes_after_the_title() -> None:
    slack = InMemorySlack()
    created = _created(slack)

    slack.transport().write_section(
        CANVAS, SectionRequest(AddSection("note", "Read this first.\n", None), created.raw_sections, STAMP)
    )

    assert (_edits(slack), slack.markdown_of(CANVAS)) == (
        [
            {
                "operation": "insert_after",
                "section_id": _section(CANVAS, 0, 0),
                "document_content": {"type": "markdown", "markdown": "Read this first.\n"},
            }
        ],
        STORED.replace("Welcome", "Read this first.\n\nWelcome"),
    )


def test_a_section_moved_to_the_end_lands_before_the_stamp() -> None:
    slack = InMemorySlack()
    created = _created(slack)
    raw = dict(created.raw_sections)

    slack.transport().write_section(
        CANVAS, SectionRequest(ReplaceSection("intro", raw["intro"], raw["intro"], "planting"), raw, STAMP)
    )

    assert slack.markdown_of(CANVAS) == STORED.replace("Welcome to the garden.\n\n", "").replace(
        f"\n\n{STAMP_LINE}", f"\n\nWelcome to the garden.\n\n{STAMP_LINE}"
    )


def test_a_removed_section_only_deletes_its_blocks() -> None:
    slack = InMemorySlack()
    created = _created(slack)
    raw = dict(created.raw_sections)

    written = slack.transport().write_section(CANVAS, _removing_tools(raw))

    assert ([edit["operation"] for edit in _edits(slack)], list(written.raw_sections)) == (
        ["delete", "delete"],
        ["intro", "planting"],
    )


def test_a_section_write_after_a_hand_edit_elsewhere_writes_nothing() -> None:
    slack = InMemorySlack()
    created = _created(slack)
    slack.edit_by_hand(CANVAS, "Welcome to the garden.", "Welcome, friends.")
    raw = dict(created.raw_sections)

    with pytest.raises(WriteRejectedError) as raised:
        slack.transport().write_section(
            CANVAS, SectionRequest(ReplaceSection("planting", raw["planting"], "Sow.\n", "tools"), raw, STAMP)
        )

    assert (str(raised.value), _edits(slack)) == (
        f"Slack canvas {CANVAS} changed after skaldr read it, so nothing was written; publish again",
        [],
    )


def test_a_section_write_quoting_text_the_canvas_no_longer_holds_writes_nothing() -> None:
    slack = InMemorySlack()
    created = _created(slack)
    raw = dict(created.raw_sections)

    with pytest.raises(WriteRejectedError) as raised:
        slack.transport().write_section(
            CANVAS,
            SectionRequest(ReplaceSection("planting", "Sow in winter.\n", "Sow.\n", "tools"), raw, STAMP),
        )

    assert (str(raised.value), _edits(slack)) == (
        f"Slack canvas {CANVAS} no longer holds section planting as skaldr read it, so nothing was written; "
        "publish again",
        [],
    )


def test_a_section_list_that_does_not_match_the_markdown_stops_before_any_write() -> None:
    slack = InMemorySlack(html_lists_one_section_less_after=0)
    created = _created(slack)
    raw = dict(created.raw_sections)

    with pytest.raises(WriteRejectedError) as raised:
        slack.transport().write_section(CANVAS, _removing_tools(raw))

    assert (str(raised.value), _edits(slack)) == (
        f"Slack lists 6 sections for canvas {CANVAS} but its Markdown holds 7 blocks, so skaldr cannot tell "
        "which to change; nothing was written",
        [],
    )


def test_a_section_list_that_stops_matching_halfway_says_the_canvas_is_partly_written() -> None:
    slack = InMemorySlack(html_lists_one_section_less_after=1)
    created = _created(slack)
    raw = dict(created.raw_sections)

    with pytest.raises(ConnectorError) as raised:
        slack.transport().write_section(CANVAS, _removing_tools(raw))

    assert (type(raised.value), str(raised.value), len(_edits(slack))) == (
        ConnectorError,
        f"Slack lists 5 sections for canvas {CANVAS} but its Markdown holds 6 blocks, so skaldr cannot tell "
        "which to change; the canvas is partly written, so publish again to finish",
        1,
    )


def test_a_section_write_puts_a_missing_stamp_back_at_the_end() -> None:
    slack = InMemorySlack()
    canvas_id = slack.add_canvas(TITLE_TEXT, "Welcome to the garden.\n")
    transport = slack.transport()
    read = transport.read_item(
        canvas_id, ItemContent(title=TITLE_TEXT, sections={"intro": "Welcome to the garden.\n"})
    )

    written = transport.write_section(
        canvas_id, SectionRequest(AddSection("tools", "Spade.\n", "intro"), read.raw_sections, STAMP)
    )

    assert (written.stamp, slack.markdown_of(canvas_id)) == (
        STAMP,
        f"# {TITLE_TEXT}\n\nWelcome to the garden.\n\nSpade.\n\n{STAMP_LINE}\n",
    )


def test_a_content_write_replaces_every_block_between_the_title_and_the_stamp() -> None:
    slack = InMemorySlack()
    created = _created(slack)

    slack.transport().write_content(
        CANVAS, ContentWrite({"tools": "Spade.\n", "planting": "Sow.\n"}, created.raw_sections, STAMP)
    )

    assert ([edit["operation"] for edit in _edits(slack)], slack.markdown_of(CANVAS)) == (
        ["delete"] * 5 + ["insert_after"],
        f"# {TITLE_TEXT}\n\nSpade.\n\nSow.\n\n{STAMP_LINE}\n",
    )


def test_a_new_title_renames_the_canvas() -> None:
    slack = InMemorySlack()
    _created(slack)
    transport = slack.transport()
    transport.read_item(CANVAS, CONTENT)

    written = transport.write_fields(CANVAS, FieldsWrite("Garden guide", {}, TITLE_TEXT, {}, STAMP))

    assert (_edits(slack), written.comparable.title) == (
        [{"operation": "rename", "title_content": {"type": "markdown", "markdown": "Garden guide"}}],
        "Garden guide",
    )


@pytest.mark.parametrize(
    ("fields", "previous", "named"),
    [
        pytest.param({"Area": "Shed"}, {}, "Area", id="set"),
        pytest.param({}, {"Area": "Shed", "Owner": "Rowan"}, "Area, Owner", id="cleared"),
    ],
)
def test_a_canvas_has_no_fields_to_write(fields: JsonFields, previous: JsonFields, named: str) -> None:
    slack = InMemorySlack()
    _created(slack)

    with pytest.raises(WriteRejectedError) as raised:
        slack.transport().write_fields(CANVAS, FieldsWrite(TITLE_TEXT, fields, TITLE_TEXT, previous, STAMP))

    assert (str(raised.value), _edits(slack)) == (
        f"a Slack canvas has no fields, so skaldr cannot change {named} on canvas {CANVAS}",
        [],
    )


def test_a_fields_write_for_another_document_section_is_refused() -> None:
    slack = InMemorySlack()
    _created(slack)

    with pytest.raises(WriteRejectedError) as raised:
        slack.transport().write_fields(
            CANVAS, FieldsWrite("Garden guide", {}, TITLE_TEXT, {}, Stamp("garden-handbook", "tools"))
        )

    assert (str(raised.value), _edits(slack)) == (
        f"Slack canvas {CANVAS} is not stamped with doc_id 'garden-handbook', section 'tools'",
        [],
    )


def test_archiving_renames_the_canvas_and_leaves_one_line_and_is_harmless_twice() -> None:
    slack = InMemorySlack()
    _created(slack)
    transport = slack.transport()

    transport.archive_item(CANVAS)
    first = _edits(slack)
    slack.forget_requests()
    transport.archive_item(CANVAS)

    assert (first, _edits(slack), slack.markdown_of(CANVAS)) == (
        [
            {
                "operation": "rename",
                "title_content": {"type": "markdown", "markdown": f"{TITLE_TEXT} (archived by skaldr)"},
            },
            {
                "operation": "replace",
                "document_content": {"type": "markdown", "markdown": f"{archived_line('garden-handbook')}\n"},
            },
        ],
        [],
        f"# {TITLE_TEXT} (archived by skaldr)\n\n{archived_line('garden-handbook')}\n",
    )


def test_an_archived_canvas_reads_as_not_found() -> None:
    slack = InMemorySlack()
    _created(slack)
    transport = slack.transport()
    transport.archive_item(CANVAS)

    with pytest.raises(ItemNotFoundError, match=f"^Slack canvas {CANVAS} was archived by skaldr$"):
        transport.read_item(CANVAS, CONTENT)


def test_archiving_a_canvas_renamed_with_the_marker_keeps_one_marker() -> None:
    slack = InMemorySlack()
    _created(slack)
    slack.rename_by_hand(CANVAS, f"{TITLE_TEXT} (archived by skaldr)")

    slack.transport().archive_item(CANVAS)

    assert [edit["operation"] for edit in _edits(slack)] == ["replace"]


def test_archiving_a_canvas_that_is_gone_sends_nothing() -> None:
    slack = InMemorySlack()

    slack.transport().archive_item("F999999999")

    assert slack.writes() == []


def test_a_release_deletes_the_blocks_skaldr_published_and_its_stamp_and_keeps_what_people_added() -> None:
    slack = InMemorySlack()
    created = _created(slack)
    slack.add_block_by_hand(CANVAS, 2, "Bring gloves.")
    transport = slack.transport()
    read = transport.read_item(CANVAS, CONTENT)

    transport.release_item(CANVAS, Release(read.raw_sections, ()))
    released = transport.read_item(CANVAS, CONTENT)

    assert (created.stamp, released.stamp, dict(released.raw_sections), slack.markdown_of(CANVAS)) == (
        STAMP,
        None,
        {UNKEYED_SECTION: "Bring gloves.\n"},
        f"# {TITLE_TEXT}\n\nBring gloves.\n",
    )


def test_an_unchanged_canvas_reports_no_edit_from_one_read() -> None:
    slack = InMemorySlack()
    created = _created(slack)

    reported = slack.transport().parts_edited_after(CANVAS, created.marker, CONTENT)

    assert (reported, slack.calls()) == ((), ["canvases.getContent markdown"])


def test_a_canvas_edited_after_the_marker_reports_the_title_and_section_that_changed() -> None:
    slack = InMemorySlack()
    created = _created(slack)
    slack.rename_by_hand(CANVAS, "Garden notes")
    slack.edit_by_hand(CANVAS, "Sow in spring.", "Sow in June.")

    reported = slack.transport().parts_edited_after(CANVAS, created.marker, created.comparable)

    assert reported == (TITLE, section_part("planting"))


def test_a_canvas_is_linked_at_its_workspace_address_and_the_workspace_is_asked_once() -> None:
    slack = InMemorySlack()
    transport = slack.transport()

    links = [transport.item_link(CANVAS, TITLE_TEXT), transport.item_link("F000000002", "Tools")]

    assert (links, slack.calls()) == (
        [ItemLink(CANVAS_LINK, TITLE_TEXT), ItemLink(CANVAS_LINK.replace(CANVAS, "F000000002"), "Tools")],
        ["auth.test"],
    )


def test_links_rewrite_the_stamp_block_in_place() -> None:
    slack = InMemorySlack()
    _created(slack)

    written = slack.transport().write_links(CANVAS, LinksWrite(STAMP, (DEMO_12,)))

    assert (written, [edit["operation"] for edit in _edits(slack)], slack.markdown_of(CANVAS)) == (
        (DEMO_12,),
        ["delete", "insert_after"],
        STORED.replace(
            STAMP_LINE, f"{STAMP_LINE} · Jira [DEMO-12](https://example.atlassian.net/browse/DEMO-12)"
        ),
    )


def test_links_on_an_unstamped_canvas_add_the_stamp_at_the_end() -> None:
    slack = InMemorySlack()
    canvas_id = slack.add_canvas("Blank canvas", "Welcome.\n")

    slack.transport().write_links(canvas_id, LinksWrite(STAMP, (DEMO_12,)))

    assert slack.markdown_of(canvas_id) == (
        "# Blank canvas\n\nWelcome.\n\n"
        f"{STAMP_LINE} · Jira [DEMO-12](https://example.atlassian.net/browse/DEMO-12)\n"
    )


def test_writing_into_a_canvas_renames_it_and_replaces_its_content() -> None:
    slack = InMemorySlack()
    canvas_id = slack.add_canvas("Blank canvas")
    transport = slack.transport()
    read = transport.read_item(canvas_id, ItemContent(title=""))

    created = transport.create_item(
        NewItem(UNLINKED, STAMP, CONTENT, into_id=canvas_id, into_raw_sections=read.raw_sections)
    )

    assert (created.item_id, _edits(slack)[-2:], slack.markdown_of(canvas_id), slack.messages) == (
        canvas_id,
        [
            {
                "operation": "replace",
                "document_content": {
                    "type": "markdown",
                    "markdown": "Welcome to the garden.\n\n## Tools\n\n- Spade.\n- Rake.\n\n## Planting\n\n"
                    f"Sow in spring.\n\n{STAMP_LINE}\n",
                },
            },
            {"operation": "rename", "title_content": {"type": "markdown", "markdown": TITLE_TEXT}},
        ],
        STORED,
        [],
    )
