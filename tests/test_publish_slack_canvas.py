import pytest

from skaldr.publish.slack.canvas_markdown import (
    UNKEYED_SECTION,
    CanvasBlock,
    archived_line,
    canvas_blocks,
    canvas_body,
    canvas_markdown_of,
    canvas_stamp_line,
    comparable_block,
    comparable_text,
    keyed_canvas,
)
from skaldr.publish.transport import ShownLink, Stamp

STAMP = Stamp("garden-handbook", None)
STAMP_LINE = "Published with skaldr from document garden-handbook"
INTRO = "Welcome to the garden.\n"
TOOLS = "## Tools\n\n- Spade.\n- Rake.\n"
PLANTING = "## Planting\n\nSow in spring.\n"
LAYOUT = {"intro": INTRO, "tools": TOOLS, "planting": PLANTING}
STORED = (
    "# Garden handbook\n\n"
    "Welcome to the garden.\n\n"
    "## Tools\n\n"
    "* Spade.\n* Rake.\n\n"
    "## Planting\n\n"
    "Sow in spring.\n\n"
    f"{STAMP_LINE}\n"
)
DEMO_12 = ShownLink(
    service="jira", item_id="DEMO-12", url="https://example.atlassian.net/browse/DEMO-12", title="DEMO-12"
)
HANDBOOK_PAGE = ShownLink(
    service="notion",
    item_id="0123456789abcdef0123456789abcdef",
    url="https://www.notion.so/0123456789abcdef0123456789abcdef",
    title="Garden handbook",
)


@pytest.mark.parametrize(
    ("markdown", "blocks"),
    [
        pytest.param("", [], id="empty"),
        pytest.param("\n\n", [], id="only-blank-lines"),
        pytest.param("One.\n\nTwo.\n", ["One.", "Two."], id="paragraphs"),
        pytest.param("One.\n\n\n\nTwo.", ["One.", "Two."], id="several-blank-lines-and-no-final-newline"),
        pytest.param("first\\\nsecond\n", ["first\\\nsecond"], id="hard-break-keeps-one-block"),
        pytest.param(
            "```bash\nrun\n\nagain\n```\n\nAfter.\n",
            ["```bash\nrun\n\nagain\n```", "After."],
            id="fence-with-a-blank-line",
        ),
        pytest.param(
            "````\n```\n\n````\n\nAfter.\n",
            ["````\n```\n\n````", "After."],
            id="longer-fence-holds-a-shorter",
        ),
        pytest.param(
            "::: {.callout}\nFirst.\n\nSecond.\n:::\n\nAfter.\n",
            ["::: {.callout}\nFirst.\n\nSecond.\n:::", "After."],
            id="callout-with-a-blank-line",
        ),
        pytest.param(
            "::: {.layout}\n::: {.column}\nLeft.\n\n:::\n::: {.column}\nRight.\n:::\n:::\n\nAfter.\n",
            ["::: {.layout}\n::: {.column}\nLeft.\n\n:::\n::: {.column}\nRight.\n:::\n:::", "After."],
            id="nested-containers",
        ),
        pytest.param("* a\n\n \n\n* b\n", ["* a", " ", "* b"], id="a-space-paragraph-is-a-block"),
        pytest.param(
            "|A|B|\n|  ---  |  ---  |\n|1|2|\n\n\nAfter.\n",
            ["|A|B|\n|  ---  |  ---  |\n|1|2|", "After."],
            id="table-and-its-extra-blank-line",
        ),
    ],
)
def test_a_canvas_splits_into_the_blocks_slack_keeps_apart(markdown: str, blocks: list[str]) -> None:
    assert canvas_blocks(markdown) == blocks


@pytest.mark.parametrize(
    ("block", "comparable"),
    [
        pytest.param("- Spade.\n- Rake.", "* Spade.\n* Rake.", id="dash-bullets"),
        pytest.param("- [ ] water\n  - [x] seed", "* [ ] water\n  * [x] seed", id="nested-check-items"),
        pytest.param("+ Spade.", "* Spade.", id="plus-bullet"),
        pytest.param("---", "---", id="divider"),
        pytest.param(
            "| A | B |\n| --- | :---: |\n| 1 | 2 \\| 3 |",
            "|A|B|\n|---|---|\n|1|2 \\| 3|",
            id="table-as-sent",
        ),
        pytest.param("|A|B|\n|  ---  |  ---  |\n|1|2|", "|A|B|\n|---|---|\n|1|2|", id="table-as-stored"),
        pytest.param(
            "Ask ![](@U0EXAMPLE1) in ![](#C0EXAMPLE1).", "Ask <@U0EXAMPLE1> in <#C0EXAMPLE1>.", id="mentions"
        ),
        pytest.param("first\\\nsecond", "first\nsecond", id="hard-break"),
        pytest.param("Sow.   ", "Sow.", id="trailing-spaces"),
        pytest.param("&nbsp;", "", id="list-separator-as-sent"),
        pytest.param(" ", "", id="list-separator-as-stored"),
        pytest.param("\xa0", "", id="no-break-space"),
        pytest.param("one\n \ntwo", "one\ntwo", id="space-line-inside-a-paragraph"),
        pytest.param(
            "```text\n- keep  \n![](@U0EXAMPLE1)\n```", "```text\n- keep  \n![](@U0EXAMPLE1)\n```", id="code"
        ),
        pytest.param("::: {.callout}\n- one\n\n:::", "::: {.callout}\n* one\n:::", id="callout"),
    ],
)
def test_a_block_compares_in_the_form_slack_stores(block: str, comparable: str) -> None:
    assert comparable_block(block) == comparable


def test_a_comparable_text_is_its_own_comparable_text() -> None:
    once = comparable_text("- a\n\n&nbsp;\n\n- [x] b\n\n| A |\n| --- |\n| 1 \\| 2 |\n\n```\n\n- c\n```\n")

    assert (once, comparable_text(once)) == (
        "* a\n\n* [x] b\n\n|A|\n|---|\n|1 \\| 2|\n\n```\n\n- c\n```\n",
        "* a\n\n* [x] b\n\n|A|\n|---|\n|1 \\| 2|\n\n```\n\n- c\n```\n",
    )


def test_an_empty_text_compares_as_nothing() -> None:
    assert (comparable_text(""), comparable_text("&nbsp;\n")) == ("", "")


def test_sections_are_written_as_blocks_apart_from_one_another() -> None:
    assert canvas_markdown_of([INTRO, "", TOOLS, f"{STAMP_LINE}"]) == (
        f"Welcome to the garden.\n\n## Tools\n\n- Spade.\n- Rake.\n\n{STAMP_LINE}\n"
    )


def test_a_canvas_reads_keyed_by_section_under_its_title_and_over_its_stamp() -> None:
    keyed = keyed_canvas(STORED + "\nA note someone added below.\n", LAYOUT)

    assert (
        keyed.title,
        dict(keyed.raw_sections),
        dict(keyed.sections),
        keyed.stamp,
        keyed.links,
        [(block.key, block.role) for block in keyed.blocks],
        keyed.content_start,
        keyed.stamp_at,
    ) == (
        "Garden handbook",
        {
            "intro": "Welcome to the garden.\n",
            "tools": "## Tools\n\n* Spade.\n* Rake.\n",
            "planting": "## Planting\n\nSow in spring.\n",
        },
        {
            "intro": "Welcome to the garden.\n",
            "tools": "## Tools\n\n* Spade.\n* Rake.\n",
            "planting": "## Planting\n\nSow in spring.\n",
        },
        STAMP,
        (),
        [
            (None, "title"),
            ("intro", "published"),
            ("tools", "published"),
            ("tools", "published"),
            ("planting", "published"),
            ("planting", "published"),
            (None, "stamp"),
            (None, "below"),
        ],
        1,
        6,
    )


def test_a_block_edited_by_hand_stays_in_its_section_as_added() -> None:
    edited = STORED.replace("Sow in spring.", "Sow in June.")

    keyed = keyed_canvas(edited, LAYOUT)

    assert (keyed.sections["planting"], keyed.blocks[5]) == (
        "## Planting\n\nSow in June.\n",
        CanvasBlock("Sow in June.", "planting", "added"),
    )


def test_a_block_added_by_hand_between_sections_opens_the_next_one_and_inside_a_section_joins_it() -> None:
    added = STORED.replace("* Rake.\n\n", "* Rake.\n\nBring gloves.\n\n").replace(
        "## Planting\n\n", "## Planting\n\nIn the north beds:\n\n"
    )

    keyed = keyed_canvas(added, LAYOUT)

    assert (keyed.raw_sections["tools"], keyed.raw_sections["planting"]) == (
        "## Tools\n\n* Spade.\n* Rake.\n",
        "Bring gloves.\n\n## Planting\n\nIn the north beds:\n\nSow in spring.\n",
    )


def test_a_separator_paragraph_belongs_to_the_section_around_it() -> None:
    layout = {"lists": "- a\n\n&nbsp;\n\n- [ ] b\n"}

    keyed = keyed_canvas("# T\n\n* a\n\n \n\n* [ ] b\n", layout)

    assert (dict(keyed.raw_sections), [block.role for block in keyed.blocks]) == (
        {"lists": "* a\n\n \n\n* [ ] b\n"},
        ["title", "published", "blank", "published"],
    )


def test_a_canvas_read_with_no_layout_keys_its_content_as_unpublished() -> None:
    keyed = keyed_canvas("# Blank page\n\nA line.\n", {})

    assert (keyed.title, dict(keyed.raw_sections), keyed.blocks[1]) == (
        "Blank page",
        {UNKEYED_SECTION: "A line.\n"},
        CanvasBlock("A line.", UNKEYED_SECTION, "added"),
    )


def test_an_empty_canvas_has_its_title_and_nothing_else() -> None:
    keyed = keyed_canvas("# Blank page\n", LAYOUT)

    assert (keyed.title, dict(keyed.raw_sections), keyed.stamp, keyed.content_start, keyed.stamp_at) == (
        "Blank page",
        {},
        None,
        1,
        None,
    )


def test_a_canvas_without_a_title_heading_has_a_blank_title() -> None:
    keyed = keyed_canvas("Welcome to the garden.\n", {"intro": INTRO})

    assert (keyed.title, keyed.content_start, dict(keyed.raw_sections)) == ("", 0, {"intro": INTRO})


def test_the_stamp_names_its_links_and_reads_them_back() -> None:
    line = canvas_stamp_line(Stamp("garden-handbook", "tools"), (DEMO_12, HANDBOOK_PAGE))

    keyed = keyed_canvas(f"# Tools\n\n## Tools\n\n{line}\n", {"tools": "## Tools\n"})

    assert (line, keyed.stamp, keyed.links) == (
        "Published with skaldr from document garden-handbook, section tools · Jira "
        "[DEMO-12](https://example.atlassian.net/browse/DEMO-12) · Notion "
        "[Garden handbook](https://www.notion.so/0123456789abcdef0123456789abcdef)",
        Stamp("garden-handbook", "tools"),
        (DEMO_12, HANDBOOK_PAGE),
    )


def test_a_link_title_is_escaped_for_the_canvas() -> None:
    renamed = DEMO_12.model_copy(update={"title": "GARDEN_OPS [north]"})

    assert canvas_stamp_line(STAMP, (renamed,)) == (
        "Published with skaldr from document garden-handbook · Jira "
        "[GARDEN\\_OPS \\[north\\]](https://example.atlassian.net/browse/DEMO-12)"
    )


def test_stamp_text_inside_a_code_block_is_content() -> None:
    code = f"```\n{STAMP_LINE}\n```"

    keyed = keyed_canvas(f"# T\n\n{code}\n", {"code": code + "\n"})

    assert (keyed.stamp, dict(keyed.raw_sections)) == (None, {"code": code + "\n"})


def test_the_last_stamp_counts_and_an_earlier_one_is_content() -> None:
    other = "Published with skaldr from document kitchen-rota"

    keyed = keyed_canvas(f"# T\n\n{INTRO}\n{other}\n\n{STAMP_LINE}\n", {"intro": INTRO})

    assert (keyed.stamp, keyed.raw_sections["intro"]) == (STAMP, f"{INTRO}\n{other}\n")


@pytest.mark.parametrize(
    ("markdown", "archived", "opens_with_the_archived_line"),
    [
        pytest.param(
            f"# Garden handbook (archived by skaldr)\n\n{archived_line('garden-handbook')}\n",
            True,
            True,
            id="archived",
        ),
        pytest.param(f"# Garden handbook\n\n{archived_line(None)}\n", False, True, id="not-yet-renamed"),
        pytest.param(
            f"# T\n\n{archived_line(None)}\n\nA note kept below.\n", False, True, id="content-kept-below"
        ),
        pytest.param("# Garden handbook (archived by skaldr)\n\nWelcome.\n", True, False, id="title-marker"),
        pytest.param(
            f"# T\n\nWelcome.\n\n{archived_line(None)}\n", False, False, id="archived-line-not-first"
        ),
        pytest.param(
            f"# T\n\n{archived_line(None)} Welcome back.\n", False, False, id="archived-words-then-more-text"
        ),
        pytest.param(STORED, False, False, id="published"),
    ],
)
def test_a_canvas_is_archived_by_its_title_marker_and_an_unfinished_archive_by_its_opening_line(
    markdown: str, archived: bool, opens_with_the_archived_line: bool
) -> None:
    keyed = keyed_canvas(markdown, LAYOUT)

    assert (keyed.archived, keyed.opens_with_the_archived_line) == (archived, opens_with_the_archived_line)


@pytest.mark.parametrize(
    ("keys", "position"),
    [
        pytest.param(["intro", "tools"], 4, id="after-the-last-block-of-the-key-before"),
        pytest.param(["intro", "tools", "harvest"], 4, id="a-key-the-canvas-does-not-hold-is-passed-over"),
        pytest.param(["harvest", "pruning"], 1, id="no-key-held-goes-after-the-title"),
        pytest.param([], 1, id="first-goes-after-the-title"),
    ],
)
def test_a_section_goes_after_the_last_block_of_the_nearest_key_before_it_that_the_canvas_holds(
    keys: list[str], position: int
) -> None:
    assert keyed_canvas(STORED, LAYOUT).position_after(keys) == position


def test_the_archived_line_names_the_document() -> None:
    assert (archived_line("garden-handbook"), archived_line(None)) == (
        "skaldr archived this canvas: the document garden-handbook no longer publishes here.",
        "skaldr archived this canvas: the document no longer publishes here.",
    )


@pytest.mark.parametrize(
    ("raws", "body"),
    [
        pytest.param(["Sow.", "* Spade."], "Sow.\n\n* Spade.\n", id="blocks-are-blank-line-separated"),
        pytest.param(["* One.", "* Two."], "* One.\n\n&nbsp;\n\n* Two.\n", id="two-lists-are-kept-apart"),
        pytest.param(
            ["1. One.", "- Two."], "1. One.\n\n&nbsp;\n\n- Two.\n", id="a-numbered-and-a-bullet-list"
        ),
        pytest.param(
            ["* One.", " ", "* Two."], "* One.\n\n&nbsp;\n\n* Two.\n", id="a-stored-separator-is-sent-as-one"
        ),
        pytest.param(
            ["* One.", "Sow.", "* Two."], "* One.\n\nSow.\n\n* Two.\n", id="a-paragraph-keeps-lists-apart"
        ),
        pytest.param([], "&nbsp;\n", id="no-blocks-is-one-blank-paragraph"),
    ],
)
def test_a_canvas_body_is_its_blocks_with_two_lists_in_a_row_kept_apart(raws: list[str], body: str) -> None:
    assert canvas_body(raws) == body
