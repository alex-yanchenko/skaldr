import pytest

from skaldr.publish.notion.page_markdown import (
    UNKEYED_SECTION,
    KeyedPage,
    Replacement,
    carried_into,
    comparable_text,
    joined,
    keyed_page,
    release_replacement,
    section_replacement,
    stamp_line,
    without_comment_markers,
)
from skaldr.publish.transport import Stamp

INTRO = "## Welcome\nWelcome to the garden.\n"
TOOLS = "## Tools\n- Spade.\n- Rake.\n"
PLANTING = "## Planting\nSow in spring.\n"
LAYOUT = {"intro": INTRO, "tools": TOOLS, "planting": PLANTING}
STAMP = Stamp("garden-handbook", None)
STAMP_LINE = 'Published with skaldr from document garden-handbook {color="gray"}\n'
CHILD = '<page url="https://www.notion.so/Seeds-0123456789abcdef0123456789abcdef">Seeds</page>'
COMMENTED = '<span discussion-urls="discussion://pages/1/discussions/2">Sow in spring.</span>'


def _page(*lines: str) -> str:
    return "".join(lines)


@pytest.mark.parametrize(
    ("text", "without"),
    [
        pytest.param("Sow in spring.", "Sow in spring.", id="no-marker"),
        pytest.param(COMMENTED, "Sow in spring.", id="marker-around-the-text"),
        pytest.param(
            'Sow <span discussion-urls="d://1">in</span> spring <span discussion-urls="d://2">soon</span>.',
            "Sow in spring soon.",
            id="two-markers",
        ),
        pytest.param(
            '<span discussion-urls="d://1">Sow <span color="red">in</span> spring</span>.',
            'Sow <span color="red">in</span> spring.',
            id="marker-around-a-colored-span",
        ),
        pytest.param(
            '<span color="red" discussion-urls="d://1">Sow</span> now.',
            '<span color="red">Sow</span> now.',
            id="marker-beside-another-attribute",
        ),
        pytest.param(
            '<span discussion-urls="d://1">Sow</span',
            '<span discussion-urls="d://1">Sow</span',
            id="unclosed-marker-left-as-it-is",
        ),
    ],
)
def test_comment_markers_are_taken_out_and_their_text_kept(text: str, without: str) -> None:
    assert without_comment_markers(text) == without


@pytest.mark.parametrize(
    ("text", "comparable"),
    [
        pytest.param("", "", id="nothing"),
        pytest.param("Welcome.", "Welcome.\n", id="a-last-line-without-its-newline"),
        pytest.param("Welcome.\n\n\nBye.\n", "Welcome.\nBye.\n", id="blank-lines-outside-code"),
        pytest.param(
            "```text\na\n\n  b\n```\n", "```text\na\n\n  b\n```\n", id="top-level-code-kept-exactly"
        ),
        pytest.param(
            "- Steps\n\t```bash\n\trake\n\t\tdeep\n\n\t```\n",
            "- Steps\n\t```bash\nrake\ndeep\n\n```\n",
            id="indented-code-indentation-ignored",
        ),
        pytest.param(
            '<table header-row="true">\n\t<tr>\n\t\t<td>a</td>\n\t</tr>\n</table>\n',
            '<table header-row="true">\n<tr>\n<td>a</td>\n</tr>\n</table>\n',
            id="table-indentation-ignored",
        ),
        pytest.param(
            '<callout icon="💡">\n\t<table>\n  <tr>\n\t</tr>\n\t</table>\n\tAfter.\n</callout>\n',
            '<callout icon="💡">\n<table>\n<tr>\n</tr>\n</table>\n\tAfter.\n</callout>\n',
            id="nested-table-then-indentation-counts-again",
        ),
        pytest.param("Welcome.\n<empty-block/>\n<empty-block/>\n", "Welcome.\n", id="trailing-empty-blocks"),
        pytest.param("<empty-block/>\n- One\n", "<empty-block/>\n- One\n", id="leading-empty-block-kept"),
    ],
)
def test_comparable_text_mirrors_how_notion_normalises_markdown(text: str, comparable: str) -> None:
    assert comparable_text(text) == comparable


def test_comparable_text_is_idempotent() -> None:
    text = "- Steps\n\t```bash\n\trake\n\n\t```\n<table>\n\t<tr>\n\t</tr>\n</table>\n<empty-block/>\n"

    assert comparable_text(comparable_text(text)) == comparable_text(text)


def test_a_page_as_published_reads_back_keyed_like_the_layout() -> None:
    page = _page(INTRO, TOOLS, PLANTING, STAMP_LINE, CHILD, "\n<empty-block/>")

    assert keyed_page(page, LAYOUT) == KeyedPage(
        raw_sections=LAYOUT,
        sections=LAYOUT,
        stamp=STAMP,
        stamp_line=STAMP_LINE,
        child_ids=("0123456789abcdef0123456789abcdef",),
    )


def test_a_hand_edit_inside_a_section_belongs_to_that_section() -> None:
    edited = "## Tools\n- Spade.\n- Hoe.\n"
    page = _page(INTRO, edited, PLANTING, STAMP_LINE)

    assert keyed_page(page, LAYOUT).raw_sections == {"intro": INTRO, "tools": edited, "planting": PLANTING}


def test_text_added_between_two_sections_belongs_to_the_one_before() -> None:
    page = _page(INTRO, TOOLS, "A note.\n", PLANTING, STAMP_LINE)

    assert keyed_page(page, LAYOUT).raw_sections == {
        "intro": INTRO,
        "tools": TOOLS + "A note.\n",
        "planting": PLANTING,
    }


def test_text_added_before_the_first_section_belongs_to_it() -> None:
    page = _page("A note.\n", INTRO, TOOLS, PLANTING, STAMP_LINE)

    assert keyed_page(page, LAYOUT).raw_sections["intro"] == "A note.\n" + INTRO


def test_a_section_deleted_by_hand_is_absent() -> None:
    page = _page(INTRO, PLANTING, STAMP_LINE)

    assert keyed_page(page, LAYOUT).raw_sections == {"intro": INTRO, "planting": PLANTING}


def test_comment_markers_stay_in_the_raw_text_and_leave_the_comparable_one() -> None:
    commented = f"## Planting\n{COMMENTED}\n"
    page = _page(INTRO, TOOLS, commented, STAMP_LINE)

    keyed = keyed_page(page, LAYOUT)

    assert (keyed.raw_sections["planting"], keyed.sections["planting"]) == (commented, PLANTING)


def test_blank_lines_notion_kept_stay_in_the_raw_text_so_sections_join_back_into_the_page() -> None:
    page = _page(INTRO, "\n", TOOLS, PLANTING, STAMP_LINE)

    keyed = keyed_page(page, LAYOUT)

    assert (
        keyed.raw_sections["intro"],
        keyed.sections,
        joined([*keyed.raw_sections.values(), STAMP_LINE]),
    ) == (
        INTRO + "\n",
        LAYOUT,
        page,
    )


def test_a_page_whose_layout_names_no_section_holds_one_unkeyed_section() -> None:
    page = _page("Notes from a person.\n", "\n<empty-block/>")

    assert keyed_page(page, {}) == KeyedPage(
        raw_sections={UNKEYED_SECTION: "Notes from a person.\n\n<empty-block/>"},
        sections={UNKEYED_SECTION: "Notes from a person.\n"},
        stamp=None,
        stamp_line=None,
        child_ids=(),
    )


def test_an_empty_page_holds_no_section() -> None:
    assert keyed_page("", LAYOUT) == KeyedPage({}, {}, None, None, ())


def test_the_stamp_names_the_section_an_item_holds() -> None:
    line = stamp_line(Stamp("garden-handbook", "tools"))

    keyed = keyed_page(_page(TOOLS, line), {"tools": TOOLS})

    assert (line, keyed.stamp, keyed.raw_sections) == (
        'Published with skaldr from document garden-handbook, section tools {color="gray"}\n',
        Stamp("garden-handbook", "tools"),
        {"tools": TOOLS},
    )


def test_stamp_text_inside_a_code_block_is_content_not_a_stamp() -> None:
    code = "```text\n" + STAMP_LINE + "```\n"

    keyed = keyed_page(code, {"code": code})

    assert (keyed.stamp, keyed.raw_sections) == (None, {"code": code})


def test_the_last_stamp_on_the_page_counts_and_an_earlier_one_is_content() -> None:
    other = 'Published with skaldr from document kitchen-rota {color="gray"}\n'

    keyed = keyed_page(_page(INTRO, other, STAMP_LINE), {"intro": INTRO})

    assert (keyed.stamp, keyed.raw_sections) == (STAMP, {"intro": INTRO + other})


@pytest.mark.parametrize(
    "below",
    [
        pytest.param([f"{CHILD}\n", "<empty-block/>"], id="child-then-empty-block"),
        pytest.param(["<empty-block/>\n", CHILD], id="empty-block-then-child"),
        pytest.param([f"{CHILD}\n", "A person's note.\n", "<empty-block/>"], id="a-persons-text"),
        pytest.param(["\n", "A person's note."], id="text-after-a-blank-line"),
    ],
)
def test_whatever_follows_the_stamp_belongs_to_no_section(below: list[str]) -> None:
    keyed = keyed_page(_page(INTRO, STAMP_LINE, *below), {"intro": INTRO})

    assert (keyed.raw_sections, keyed.sections, keyed.stamp) == ({"intro": INTRO}, {"intro": INTRO}, STAMP)


def test_a_child_page_inside_a_section_stays_in_its_raw_text_and_leaves_its_comparable_text() -> None:
    tools = f"## Tools\n- Spade.\n{CHILD}\n- Rake.\n"

    keyed = keyed_page(_page(INTRO, tools, PLANTING, STAMP_LINE), LAYOUT)

    assert (keyed.raw_sections, keyed.sections, keyed.child_ids) == (
        {"intro": INTRO, "tools": tools, "planting": PLANTING},
        LAYOUT,
        ("0123456789abcdef0123456789abcdef",),
    )


def test_a_child_page_between_two_sections_belongs_to_the_one_before_so_sections_join_into_the_page() -> None:
    page = _page(INTRO, f"{CHILD}\n", TOOLS, PLANTING, STAMP_LINE)

    keyed = keyed_page(page, LAYOUT)

    assert (
        keyed.raw_sections["intro"],
        keyed.sections,
        joined([*keyed.raw_sections.values(), STAMP_LINE]),
    ) == (
        f"{INTRO}{CHILD}\n",
        LAYOUT,
        page,
    )


def test_child_pages_are_listed_in_page_order_above_and_below_the_stamp() -> None:
    other = '<page url="https://www.notion.so/Beds-fedcba9876543210fedcba9876543210">Beds</page>'

    keyed = keyed_page(_page(INTRO, f"{other}\n", STAMP_LINE, CHILD), {"intro": INTRO})

    assert keyed.child_ids == ("fedcba9876543210fedcba9876543210", "0123456789abcdef0123456789abcdef")


@pytest.mark.parametrize(
    ("raw", "text", "carried"),
    [
        pytest.param(TOOLS, "## Tools\n- Hoe.\n", "## Tools\n- Hoe.\n", id="no-child-page"),
        pytest.param(
            f"## Tools\n- Spade.\n{CHILD}\n- Rake.\n",
            "## Tools\n- Hoe.\n- Fork.\n- Rake.\n",
            f"## Tools\n- Hoe.\n{CHILD}\n- Fork.\n- Rake.\n",
            id="kept-after-as-many-lines",
        ),
        pytest.param(
            f"Intro.\n{CHILD}\n",
            "<table>\n\t<tr>\n\t\t<td>a</td>\n\t</tr>\n</table>\nAfter.\n",
            f"<table>\n\t<tr>\n\t\t<td>a</td>\n\t</tr>\n</table>\n{CHILD}\nAfter.\n",
            id="moved-past-a-table-to-the-next-block",
        ),
        pytest.param(
            f"{CHILD}\n## Tools\n", "## Tools\n- Hoe.\n", f"{CHILD}\n## Tools\n- Hoe.\n", id="first"
        ),
        pytest.param(f"## Tools\n{CHILD}\n", "", f"{CHILD}\n", id="section-removed"),
    ],
)
def test_child_pages_in_a_section_are_carried_into_its_new_text_at_a_block_boundary(
    raw: str, text: str, carried: str
) -> None:
    assert carried_into(raw, text) == carried


def test_releasing_removes_the_published_lines_and_the_stamp_and_keeps_a_persons_text_and_child_pages() -> (
    None
):
    planting = "## Planting\nSow in June.\n"
    released = _page(INTRO, "A person's note.\n", TOOLS, f"{CHILD}\n", planting, STAMP_LINE)

    replacement = release_replacement(_page(released, "Below.\n"), LAYOUT)

    assert replacement == Replacement(
        released, f"A person's note.\n{CHILD}\nSow in June.\n", ("intro", "tools", "planting")
    )


def test_releasing_a_page_skaldr_already_released_changes_nothing() -> None:
    assert release_replacement("A person's note.\n", {}) == Replacement(
        "A person's note.\n", "A person's note.\n", (UNKEYED_SECTION,)
    )


def test_a_commented_stamp_is_still_the_stamp() -> None:
    line = '<span discussion-urls="d://1">Published with skaldr from document garden-handbook</span>\n'

    assert keyed_page(_page(INTRO, line), {"intro": INTRO}).stamp == STAMP


CURRENT = [("intro", INTRO), ("tools", TOOLS), ("planting", PLANTING)]
PAGE = _page(INTRO, TOOLS, PLANTING, STAMP_LINE)
SEEDS = ("seeds", "Seeds.\n")


def _replaced(current: list[tuple[str, str]], after: list[tuple[str, str]]) -> Replacement | None:
    return section_replacement(
        current, after, joined([*(text for _, text in current), STAMP_LINE]), STAMP_LINE
    )


@pytest.mark.parametrize(
    ("after", "replacement"),
    [
        pytest.param(
            [("intro", INTRO), ("tools", "## Tools\n- Hoe.\n"), ("planting", PLANTING)],
            Replacement(TOOLS, "## Tools\n- Hoe.\n", ("tools",)),
            id="replace-one-section",
        ),
        pytest.param(
            [("intro", INTRO), ("planting", PLANTING)],
            Replacement(TOOLS, "", ("tools",)),
            id="remove-one-section",
        ),
        pytest.param(
            [("intro", INTRO), SEEDS, ("tools", TOOLS), ("planting", PLANTING)],
            Replacement("Welcome to the garden.\n", "Welcome to the garden.\nSeeds.\n", ("intro",)),
            id="add-after-a-section-anchors-on-its-last-line",
        ),
        pytest.param(
            [SEEDS, *CURRENT],
            Replacement("## Welcome\n", "Seeds.\n## Welcome\n", ("intro",)),
            id="add-first-anchors-on-the-next-sections-first-line",
        ),
        pytest.param(
            [*CURRENT, SEEDS],
            Replacement("Sow in spring.\n", "Sow in spring.\nSeeds.\n", ("planting",)),
            id="add-last-anchors-on-the-last-line-before-the-stamp",
        ),
        pytest.param(
            [("planting", PLANTING), ("intro", INTRO), ("tools", TOOLS)],
            Replacement(INTRO + TOOLS + PLANTING, PLANTING + INTRO + TOOLS, ("intro", "tools", "planting")),
            id="move-spans-both-places",
        ),
        pytest.param(CURRENT, Replacement("", ""), id="nothing-changes"),
    ],
)
def test_a_section_change_is_one_replacement_of_the_smallest_span_it_touches(
    after: list[tuple[str, str]], replacement: Replacement | None
) -> None:
    assert section_replacement(CURRENT, after, PAGE, STAMP_LINE) == replacement


@pytest.mark.parametrize(
    "last_line",
    [
        pytest.param(f"{COMMENTED}\n", id="a-comment-marker"),
        pytest.param(
            '<unknown url="https://www.notion.so/x" alt="bookmark"/>\n', id="a-block-markdown-cannot-show"
        ),
    ],
)
def test_an_added_section_anchors_past_a_neighbour_line_it_must_not_rewrite(last_line: str) -> None:
    current = [("intro", f"## Welcome\n{last_line}"), ("tools", TOOLS)]

    assert _replaced(current, [current[0], SEEDS, current[1]]) == Replacement(
        "## Tools\n", "Seeds.\n## Tools\n", ("tools",)
    )


def test_an_added_section_anchors_on_the_shortest_tail_that_appears_once() -> None:
    current = [("intro", INTRO), ("a", "Note.\nWater.\n"), ("b", "Water.\n")]

    assert _replaced(current, [*current[:2], SEEDS, current[2]]) == Replacement(
        "Note.\nWater.\n", "Note.\nWater.\nSeeds.\n", ("a",)
    )


def test_a_span_that_appears_twice_widens_until_it_appears_once() -> None:
    current = [("intro", INTRO), ("a", "Water.\n"), ("b", "Water.\n")]
    after = [("intro", INTRO), ("a", "Water.\n"), ("b", "Water daily.\n")]

    assert _replaced(current, after) == Replacement("Water.\nWater.\n", "Water.\nWater daily.\n", ("a", "b"))


def test_a_page_with_no_sections_takes_its_first_section_before_the_stamp() -> None:
    assert section_replacement([], [("intro", INTRO)], STAMP_LINE, STAMP_LINE) == Replacement(
        STAMP_LINE, INTRO + STAMP_LINE
    )


def test_a_page_with_no_sections_and_no_stamp_has_nothing_to_anchor_on() -> None:
    assert section_replacement([], [("intro", INTRO)], "", None) is None


def test_text_added_after_a_last_line_without_its_newline_starts_on_a_line_of_its_own() -> None:
    current = [("intro", "Welcome.")]

    assert section_replacement(current, [*current, ("tools", TOOLS)], "Welcome.", None) == Replacement(
        "Welcome.", "Welcome.\n" + TOOLS, ("intro",)
    )


def test_joined_pieces_each_start_on_a_new_line_and_empty_pieces_add_nothing() -> None:
    assert joined(["a", "", "b\n", "c"]) == "a\nb\nc"
