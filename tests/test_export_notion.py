import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, get_args

import pytest

from skaldr.errors import ExportInvariantError, ExportRejectedError, ReportError
from skaldr.export import EXPORT_MANIFEST, ExportResult, export_markdown, export_notion, render_export
from skaldr.export.apportion import apportioned
from skaldr.export.budget import Budget, Limit, character_budget, characters
from skaldr.export.glyphs import CALLOUT_ICON
from skaldr.export.inline import ZERO_WIDTH_SPACE
from skaldr.export.notion import (
    NOTION_DEFAULT_PAGE_WIDTH_PX,
    NOTION_ESCAPES,
    NotionChunks,
    chunk_notion,
    notion_inline,
    render_notion,
)
from skaldr.export.runs import Break, Chip, ExportRich, Gauge, SectionLink, StatusMark, TonedLabel
from skaldr.export.tree import (
    Callout,
    CodeBlock,
    Columns,
    Diagram,
    Graph,
    GraphNode,
    GridColumn,
    Heading,
    HeadingLevel,
    ListEntry,
    ListKind,
    ListNode,
    Node,
    Paragraph,
    Quote,
    Tab,
    TableCell,
    TableColumn,
    TableNode,
    TableRow,
    Tabs,
    Toggle,
    ToneName,
)
from skaldr.models import (
    AnyBlock,
    BadgeColorLiteral,
    NotionWidth,
    Report,
    load_report,
    parse_report,
    walk_blocks,
)
from skaldr.richtext import (
    AnchorLink,
    Citation,
    Code,
    DocumentLink,
    Placeholder,
    Plain,
    ScriptText,
    Styled,
    Tinted,
    parse_rich,
)
from tests.factories import (
    API_BADGES,
    BADGE_AND_STATE_BLOCKS,
    EDGE_BADGES,
    HAVE_BADGE,
    MATRIX_OF_EDGE_BADGE_LABELS,
    MATRIX_OF_EVERY_CELL_SHAPE,
    REFUSED_IN_THE_EXAMPLE,
    accepted_example,
    authored_block_types,
    folder_texts,
    heading_sections,
    in_a_grid_cell,
    in_an_open_section,
    lowered,
    make_command_request,
    make_label_table,
    make_query_request,
    make_report,
    make_section,
    make_table,
    make_toggle,
    notion_of,
    refused_block_types,
    rendered_block_count,
)
from tests.factories.capability_factory import PIE_TEXT_VARIABLES_JSON, toned_step_titled
from tests.factories.example_factory import (
    EXAMPLE,
    FIRST_REFUSAL_IN_DOCUMENT_ORDER_OF_THE_EXAMPLE,
    example_for,
    golden_of,
    golden_or_scratch_folder,
)

CHUNK_THAT_SPLITS_EVERY_SECTION = 100
CHUNK_THAT_HOLDS_THE_WHOLE_PAGE = 100_000
NESTING_TOO_DEEP_TO_PARSE = 100_000
LINKIFIED_FILE_EXTENSIONS = (
    "rs",
    "pl",
    "pm",
    "ml",
    "ai",
    "io",
    "zip",
    "mov",
    "cc",
    "ps",
    "so",
    "tf",
    "cr",
    "nu",
    "is",
    "it",
    "in",
    "me",
    "to",
    "do",
    "ar",
    "java",
    "sh",
    "py",
    "md",
)
UNLINKED_FILE_EXTENSIONS = (
    "cs",
    "go",
    "rb",
    "kt",
    "lua",
    "ex",
    "hs",
    "sql",
    "toml",
    "ini",
    "cfg",
    "txt",
    "log",
    "csv",
    "xml",
    "ts",
    "tsx",
    "jsx",
    "json",
    "yml",
    "html",
    "css",
    "c",
    "h",
    "swift",
    "php",
    "pdf",
)
NOTION_CHIP_COLOR: dict[str, str] = {
    "slate": "gray",
    "blue": "blue",
    "green": "green",
    "amber": "yellow",
    "red": "red",
    "violet": "purple",
    "teal": "brown",
    "sky": "pink",
}


def _section_text(title: str, body: str, rows: int) -> str:
    return f"## {title}\n```plain text\n" + f"{body}\n" * rows + "```\n"


def _chunked(nodes: Sequence[Node], limit: int, page_width: NotionWidth = "normal") -> NotionChunks:
    return chunk_notion(nodes, character_budget(limit), page_width)


@pytest.mark.parametrize(
    ("text", "notion"),
    [
        pytest.param("edit README.md first", "edit `README.md` first", id="markdown-file"),
        pytest.param("run scripts/setup.sh:12", "run `scripts/setup.sh:12`", id="shell-file-with-line"),
        pytest.param("see app.py", "see `app.py`", id="python-file"),
        pytest.param("see app.py:10-20 now", "see `app.py:10-20` now", id="file-with-a-line-range"),
        pytest.param("`notes.md` stays one span", "`notes.md` stays one span", id="already-code"),
        pytest.param("a readme file", "a readme file", id="no-extension"),
        *[
            pytest.param(f"see notes.{extension} now", f"see `notes.{extension}` now", id=f"{extension}-file")
            for extension in LINKIFIED_FILE_EXTENSIONS
        ],
        *[
            pytest.param(f"see notes.{extension} now", f"see notes.{extension} now", id=f"{extension}-file")
            for extension in UNLINKED_FILE_EXTENSIONS
        ],
        pytest.param("see my_tool.rs:7-9 now", "see `my_tool.rs:7-9` now", id="rust-file-with-a-line-range"),
        pytest.param("see notes.json5 now", "see notes.json5 now", id="extension-continues-past-a-match"),
        pytest.param("see notes.ini now", "see notes.ini now", id="extension-starting-with-a-match"),
        pytest.param("visit https://example.io/a now", "visit https://example.io/a now", id="a-bare-url"),
        pytest.param("mail bob@example.io now", "mail bob@example.io now", id="an-email-address"),
        pytest.param("see www.site.me now", "see www.site.me now", id="a-www-address"),
        pytest.param(
            "open notes.rs at https://example.io/a",
            "open `notes.rs` at https://example.io/a",
            id="a-file-name-beside-a-url",
        ),
        pytest.param("see NOTES.MD now", "see NOTES.MD now", id="the-extension-match-is-case-sensitive"),
    ],
)
def test_a_file_name_notion_would_turn_into_a_web_link_becomes_inline_code(text: str, notion: str) -> None:
    assert notion_inline(parse_rich(text)) == notion


def test_an_autolink_in_angle_brackets_is_left_for_the_url_it_holds() -> None:
    assert notion_inline((Plain("<https://example.io>"),)) == "\\<https://example.io\\>"


def test_a_file_name_beside_inline_code_holding_a_table_tag_in_a_cell_becomes_inline_code() -> None:
    assert notion_inline((Code("<td> notes.rs"),), in_a_table_cell=True) == "\\<td\\> `notes.rs`"


@pytest.mark.parametrize(
    ("code", "notion"),
    [
        pytest.param('{color="red"}', f'`{{{ZERO_WIDTH_SPACE}color="red"}}`', id="a-block-colour"),
        pytest.param('{color="nope"}', f'`{{{ZERO_WIDTH_SPACE}color="nope"}}`', id="any-colour-value"),
        pytest.param('{toggle="true"}', f'`{{{ZERO_WIDTH_SPACE}toggle="true"}}`', id="a-heading-toggle"),
        pytest.param(
            'x {color="red"} y {toggle="true"}',
            f'`x {{{ZERO_WIDTH_SPACE}color="red"}} y {{{ZERO_WIDTH_SPACE}toggle="true"}}`',
            id="two-attributes",
        ),
        pytest.param("{color=red}", "`{color=red}`", id="an-unquoted-value-is-kept"),
        pytest.param('{ color="red" }', '`{ color="red" }`', id="a-spaced-attribute-is-kept"),
        pytest.param('{COLOR="red"}', '`{COLOR="red"}`', id="an-upper-case-name-is-kept"),
        pytest.param("{a: 1}", "`{a: 1}`", id="plain-braces-are-kept"),
    ],
)
def test_inline_code_holding_a_block_attribute_gets_a_zero_width_space_after_the_brace(
    code: str, notion: str
) -> None:
    assert notion_inline((Code(code),)) == notion


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        pytest.param(
            Heading(2, (Plain("Head "), Code('{toggle="true"}'), Plain(" end"))),
            f'## Head `{{{ZERO_WIDTH_SPACE}toggle="true"}}` end\n',
            id="a-heading",
        ),
        pytest.param(
            Toggle((Code('{color="red"}'),), None, (Paragraph((Plain("x"),)),)),
            f'<details>\n<summary>`{{{ZERO_WIDTH_SPACE}color="red"}}`</summary>\n\tx\n</details>\n',
            id="a-toggle-summary",
        ),
    ],
)
def test_a_block_attribute_in_inline_code_is_kept_off_a_heading_and_a_toggle_summary(
    node: Node, expected: str
) -> None:
    assert render_notion([node]) == expected


def test_inline_code_holding_a_block_attribute_is_left_alone_in_a_table_cell() -> None:
    assert notion_inline((Code('{color="red"}'),), in_a_table_cell=True) == '`{color="red"}`'


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        pytest.param(
            {"type": "text", "body": 'Mid `{color="red"}` end.'},
            f'Mid `{{{ZERO_WIDTH_SPACE}color="red"}}` end.\n',
            id="a-paragraph",
        ),
        pytest.param(
            {"type": "quote", "body": 'Mid `{color="red"}` end.'},
            f'> Mid `{{{ZERO_WIDTH_SPACE}color="red"}}` end.\n',
            id="a-quote",
        ),
        pytest.param(
            {"type": "list", "items": ['Item `{color="red"}` end']},
            f'- Item `{{{ZERO_WIDTH_SPACE}color="red"}}` end\n',
            id="a-list-item",
        ),
        pytest.param(
            {"type": "callout", "tone": "info", "body": 'Mid `{color="red"}` end.'},
            f'<callout icon="{CALLOUT_ICON["info"]}" color="blue_bg">\n'
            f'\tMid `{{{ZERO_WIDTH_SPACE}color="red"}}` end.\n'
            "</callout>\n",
            id="a-callout-line",
        ),
        pytest.param(
            {"type": "text", "body": 'See [`{color="red"}`](https://example.com/a) now.'},
            f'See [`{{{ZERO_WIDTH_SPACE}color="red"}}`](https://example.com/a) now.\n',
            id="a-link-label",
        ),
        pytest.param(
            {"type": "code", "content": '{color="red"}', "lang": "text"},
            '```text\n{color="red"}\n```\n',
            id="a-fenced-block-is-kept",
        ),
    ],
)
def test_a_block_attribute_in_inline_code_cannot_colour_the_block_it_sits_in(
    block: dict[str, Any], expected: str
) -> None:
    assert notion_of([block]) == expected


@pytest.mark.parametrize(
    "tag",
    ["<td>", "<tr>", "<table>", "<td colspan=2>", "<tr/>", "a <td> b"],
)
def test_inline_code_holding_a_table_tag_is_written_as_escaped_text_in_a_table_cell(tag: str) -> None:
    written = notion_inline((Code(tag),), in_a_table_cell=True)

    assert written == tag.translate(NOTION_ESCAPES)


@pytest.mark.parametrize("text", ["<tdx>", "<track>", "<b>", "<table-of-contents>", "a<b", "td"])
def test_inline_code_holding_other_text_stays_code_in_a_table_cell(text: str) -> None:
    assert notion_inline((Code(text),), in_a_table_cell=True) == f"`{text}`"


def test_inline_code_holding_a_table_tag_stays_code_outside_a_table_cell() -> None:
    assert notion_inline((Code("<td>"),)) == "`<td>`"


def test_a_table_cell_with_inline_code_holding_a_table_tag_is_one_cell() -> None:
    table = make_table(
        [{"key": "a", "label": "Tag"}, {"key": "b", "label": "Note"}],
        rows=[{"a": "open `<td>` only", "b": "see `<table>` too"}],
    )

    assert notion_of([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**Tag**</td>\n\t\t<td>**Note**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>open \\<td\\> only</td>\n\t\t<td>see \\<table\\> too</td>\n\t</tr>\n"
        "</table>\n"
    )


CODE_HOLDING_THE_CLOSER = CodeBlock("before\n</callout>\nafter", "javascript")


@pytest.mark.parametrize(
    ("node", "message"),
    [
        pytest.param(
            Callout("info", (CODE_HOLDING_THE_CLOSER,)),
            "Notion reads the code line '</callout>' as a tag of the callout around it; "
            "the export check should have refused it",
            id="callout-closer",
        ),
        pytest.param(
            Callout("info", (CodeBlock("<callout>", ""),)),
            "Notion reads the code line '<callout>' as a tag of the callout around it; "
            "the export check should have refused it",
            id="callout-opener",
        ),
        pytest.param(
            Toggle((Plain("More"),), None, (CodeBlock("\t</details>", ""),)),
            "Notion reads the code line '</details>' as a tag of the details around it; "
            "the export check should have refused it",
            id="details-closer-after-indentation",
        ),
        pytest.param(
            Columns((GridColumn(1, (CodeBlock("</column>", ""),)),)),
            "Notion reads the code line '</column>' as a tag of the column around it; "
            "the export check should have refused it",
            id="column-closer",
        ),
        pytest.param(
            Tabs((Tab((Plain("One"),), (CodeBlock("</tab>", ""),)),)),
            "Notion reads the code line '</tab>' as a tag of the tab around it; "
            "the export check should have refused it",
            id="tab-closer",
        ),
        pytest.param(
            Callout("info", (Toggle((Plain("More"),), None, (CODE_HOLDING_THE_CLOSER,)),)),
            "Notion reads the code line '</callout>' as a tag of the callout around it; "
            "the export check should have refused it",
            id="callout-closer-two-containers-down",
        ),
    ],
)
def test_the_writer_stops_at_a_code_line_that_reads_as_a_tag_of_a_container_around_it(
    node: Node, message: str
) -> None:
    with pytest.raises(ExportInvariantError, match=f"^{re.escape(message)}$"):
        render_notion([node])


INFO_CALLOUT_OPENING = f'<callout icon="{CALLOUT_ICON["info"]}" color="blue_bg">\n'


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        pytest.param(
            CODE_HOLDING_THE_CLOSER,
            "```javascript\nbefore\n</callout>\nafter\n```\n",
            id="no-container",
        ),
        pytest.param(
            Callout("info", (CodeBlock("</details>", ""),)),
            INFO_CALLOUT_OPENING + "\t```plain text\n\t</details>\n\t```\n</callout>\n",
            id="another-containers-closer",
        ),
        pytest.param(
            Callout("info", (CodeBlock("x </callout> y", ""),)),
            INFO_CALLOUT_OPENING + "\t```plain text\n\tx </callout> y\n\t```\n</callout>\n",
            id="tag-inside-a-longer-line",
        ),
        pytest.param(
            Toggle((Plain("More"),), 2, (CODE_HOLDING_THE_CLOSER,)),
            '## More {toggle="true"}\n\t```javascript\n\tbefore\n\t</callout>\n\tafter\n\t```\n',
            id="a-heading-toggle-is-no-container",
        ),
        pytest.param(
            Callout("info", (CodeBlock("</callout >", ""),)),
            INFO_CALLOUT_OPENING + "\t```plain text\n\t</callout >\n\t```\n</callout>\n",
            id="a-different-tag",
        ),
        pytest.param(
            Toggle((Plain("More"),), None, (CodeBlock("<details>", ""),)),
            "<details>\n<summary>More</summary>\n\t```plain text\n\t<details>\n\t```\n</details>\n",
            id="a-details-opener-was-not-checked",
        ),
        pytest.param(
            Columns((GridColumn(1, (CodeBlock("<column>", ""),)),)),
            '<columns>\n\t<column ratio="1">\n\t\t```plain text\n\t\t<column>\n\t\t```\n'
            "\t</column>\n</columns>\n",
            id="a-column-opener-was-not-checked",
        ),
        pytest.param(
            Tabs((Tab((Plain("One"),), (CodeBlock("<tab>", ""),)),)),
            "<tabs>\n\t<tab>\n\t\tOne\n\t\t```plain text\n\t\t<tab>\n\t\t```\n\t</tab>\n</tabs>\n",
            id="a-tab-opener-was-not-checked",
        ),
        pytest.param(
            Toggle((Plain("More"),), None, (CodeBlock("<callout>", ""),)),
            "<details>\n<summary>More</summary>\n\t```plain text\n\t<callout>\n\t```\n</details>\n",
            id="a-callout-opener-outside-a-callout",
        ),
        pytest.param(
            Callout("info", (CodeBlock("\N{NO-BREAK SPACE}</callout>", ""),)),
            INFO_CALLOUT_OPENING + "\t```plain text\n\t\N{NO-BREAK SPACE}</callout>\n\t```\n</callout>\n",
            id="only-spaces-and-tabs-are-stripped",
        ),
    ],
)
def test_the_writer_writes_a_code_line_that_is_no_tag_of_a_container_around_it(
    node: Node, expected: str
) -> None:
    assert render_notion([node]) == expected


def test_notion_special_characters_are_escaped_in_text_but_not_in_code_or_link_urls() -> None:
    text = r"cost $5 [x] <y> {z} a|b 2^3 ~n c:\d and `a|b [c]` via [x|y](https://example.com/a_b?q=[1])"

    assert notion_inline(parse_rich(text)) == (
        r"cost \$5 \[x\] \<y\> \{z\} a\|b 2\^3 \~n c:\\d and `a|b [c]` via [x\|y](https://example.com/a_b?q=[1])"
    )


@pytest.mark.parametrize(
    ("text", "notion"),
    [
        pytest.param(
            'mid line {color="red"} here', 'mid line \\{color\\="red"\\} here', id="a-block-color-attribute"
        ),
        pytest.param("a = b", "a \\= b", id="a-spaced-equals-sign"),
        pytest.param(
            "`x = 1` and [q](https://e.com/?a=1)",
            "`x = 1` and [q](https://e.com/?a=1)",
            id="code-and-link-url",
        ),
    ],
)
def test_an_equals_sign_is_escaped_so_notion_reads_no_block_attribute(text: str, notion: str) -> None:
    assert notion_inline(parse_rich(text)) == notion


@pytest.mark.parametrize(
    ("text", "notion"),
    [
        pytest.param("ship \\_\\_init\\_\\_ now", "ship \\_\\_init\\_\\_ now", id="a-dunder-name"),
        pytest.param("a \\_private\\_ name", "a \\_private\\_ name", id="a-name-in-underscores"),
        pytest.param("snake_case", "snake\\_case", id="an-underscore-inside-a-word"),
        pytest.param("edit my_file.py", "edit `my_file.py`", id="a-file-name-is-code-and-escaped-once"),
        pytest.param("see \\_\\_init\\_\\_.py", "see `__init__.py`", id="a-dunder-file-name-is-code"),
        pytest.param("ship __init__ now", "ship **init** now", id="bare-double-underscores-are-bold"),
        pytest.param("a _private_ name", "a *private* name", id="bare-single-underscores-are-italic"),
        pytest.param(
            "`a_b` via [x_y](https://e.com/a_b)",
            "`a_b` via [x\\_y](https://e.com/a_b)",
            id="code-and-link-url",
        ),
    ],
)
def test_an_underscore_is_escaped_so_notion_reads_no_emphasis(text: str, notion: str) -> None:
    assert notion_inline(parse_rich(text)) == notion


@pytest.mark.parametrize(
    ("block", "notion"),
    [
        pytest.param(
            make_table([{"key": "a", "label": "a_b"}], rows=[{"a": "x = \\_\\_init\\_\\_"}]),
            '<table fit-page-width="true" header-row="true">\n'
            "\t<tr>\n\t\t<td>**a\\_b**</td>\n\t</tr>\n"
            "\t<tr>\n\t\t<td>x \\= \\_\\_init\\_\\_</td>\n\t</tr>\n"
            "</table>\n",
            id="a-table-cell-and-header",
        ),
        pytest.param({"type": "heading", "text": "a = _b_"}, "## a \\= \\_b\\_\n", id="a-heading"),
        pytest.param(
            make_toggle(title="x = _y_"),
            "<details>\n<summary>x \\= \\_y\\_</summary>\n\tx\n</details>\n",
            id="a-toggle-title",
        ),
        pytest.param(
            make_section("s", title="x = _y_", collapsed=True),
            '## x \\= \\_y\\_ {toggle="true"}\n\tx\n',
            id="a-heading-toggle-title",
        ),
    ],
)
def test_an_equals_sign_and_an_underscore_are_escaped_in_every_notion_text_container(
    block: dict[str, object], notion: str
) -> None:
    assert notion_of([block]) == notion


def test_inline_runs_become_notion_spans() -> None:
    runs: ExportRich = (
        Citation("a", 1, "https://example.com/a (b)"),
        Plain(" "),
        Citation("b", 2),
        Plain(" "),
        Placeholder("owner"),
        Plain(" "),
        Chip("api", "amber"),
        Plain(" "),
        SectionLink((Plain("method"),), "method"),
        Break(),
        StatusMark("blocked"),
        Gauge(3, 10),
        Plain(" wow!"),
        *parse_rich("[img](https://e.com/x.png)"),
    )

    assert notion_inline(runs) == (
        r"[\[1\]](https://example.com/a%20%28b%29) \[2\] "
        '<span color="yellow_bg">\\{\\{owner\\}\\}</span> '
        '<span color="yellow">**api**</span> method<br><span color="yellow">⏸</span>███░░░░░░░ '
        "wow\\![img](https://e.com/x.png)"
    )


def test_underline_is_a_notion_underline_span_and_scripts_are_inline_math() -> None:
    assert notion_inline(parse_rich("++new *one*++ H~2~O at 10^3^")) == (
        '<span underline="true">new *one*</span> H$`_{\\text{2}}`$O at 10$`^{\\text{3}}`$'
    )


@pytest.mark.parametrize(
    ("run", "written"),
    [
        pytest.param(ScriptText("subscript", "a_b"), "$`_{\\text{a\\_b}}`$", id="underscore"),
        pytest.param(ScriptText("subscript", "{x}"), "$`_{\\text{\\{x\\}}}`$", id="braces"),
        pytest.param(
            ScriptText("superscript", "\\$&#%~"),
            "$`^{\\text{\\textbackslash{}\\$\\&\\#\\%\\textasciitilde{}}}`$",
            id="backslash-dollar-ampersand-hash-percent-tilde",
        ),
        pytest.param(ScriptText("subscript", "^"), "$`_{\\text{\\textasciicircum{}}}`$", id="caret"),
    ],
)
def test_a_latex_special_character_in_a_script_is_escaped_inside_its_text_command(
    run: ScriptText, written: str
) -> None:
    assert notion_inline((run,)) == written


@pytest.mark.parametrize(
    ("text", "notion"),
    [
        pytest.param("[late]{tone=danger}", '<span color="red">late</span>', id="color"),
        pytest.param("[due]{bg=amber}", '<span color="yellow_bg">due</span>', id="highlight"),
        pytest.param(
            "[x]{y} [z] {tone=info}", "\\[x\\]\\{y\\} \\[z\\] \\{tone\\=info\\}", id="no-span-stays-prose"
        ),
        pytest.param(
            "[[a]{tone=danger}](https://x.io)",
            '[<span color="red">a</span>](https://x.io)',
            id="span-inside-a-link-label",
        ),
    ],
)
def test_an_attribute_span_is_a_notion_color_span(text: str, notion: str) -> None:
    assert notion_inline(parse_rich(text)) == notion


@pytest.mark.parametrize(
    ("runs", "notion"),
    [
        pytest.param(
            parse_rich("[a [x]{tone=info} b]{tone=danger}"),
            '<span color="red">a </span><span color="blue">x</span><span color="red"> b</span>',
            id="colour-inside-a-colour",
        ),
        pytest.param(
            parse_rich("[p [q]{bg=sky} r]{bg=warning}"),
            '<span color="yellow_bg">p </span><span color="pink_bg">q</span>'
            '<span color="yellow_bg"> r</span>',
            id="highlight-inside-a-highlight",
        ),
        pytest.param(
            parse_rich("[[x]{tone=info} b]{tone=danger}"),
            '<span color="blue">x</span><span color="red"> b</span>',
            id="inner-span-first",
        ),
        pytest.param(
            parse_rich("[a **[x]{tone=info}** b]{tone=danger}"),
            '<span color="red">a </span>**<span color="blue">x</span>**<span color="red"> b</span>',
            id="inner-span-in-bold",
        ),
        pytest.param(
            parse_rich("[a [[x]{tone=info} y]{tone=success} b]{tone=danger}"),
            '<span color="red">a </span><span color="blue">x</span><span color="green"> y</span>'
            '<span color="red"> b</span>',
            id="three-deep",
        ),
        pytest.param(
            (
                TonedLabel(
                    "danger", (Styled("bold", (Plain("Scan"),)), Plain(" "), *parse_rich("[cold]{tone=info}"))
                ),
            ),
            '<span color="red">**Scan** </span><span color="blue">cold</span>',
            id="author-colour-inside-a-toned-label",
        ),
    ],
)
def test_a_span_inside_a_span_of_the_same_kind_is_written_beside_it_as_notion_shows_it(
    runs: ExportRich, notion: str
) -> None:
    assert notion_inline(runs) == notion


@pytest.mark.parametrize(
    ("runs", "notion"),
    [
        pytest.param(
            parse_rich("[a ++u++ b]{tone=danger}"),
            '<span color="red">a </span><span color="red" underline="true">u</span>'
            '<span color="red"> b</span>',
            id="underline-inside-a-colour",
        ),
        pytest.param(
            parse_rich("++a [c]{tone=danger} b++"),
            '<span underline="true">a </span><span color="red" underline="true">c</span>'
            '<span underline="true"> b</span>',
            id="colour-inside-an-underline",
        ),
        pytest.param(
            parse_rich("++[h]{bg=warning}++"),
            '<span color="yellow_bg" underline="true">h</span>',
            id="highlight-filling-an-underline",
        ),
        pytest.param(
            parse_rich("[a ++b [c]{tone=info}++ d]{tone=danger}"),
            '<span color="red">a </span><span color="red" underline="true">b </span>'
            '<span color="blue" underline="true">c</span><span color="red"> d</span>',
            id="colour-inside-an-underline-inside-a-colour",
        ),
        pytest.param(
            parse_rich("++a **[c]{tone=info}**++"),
            '<span underline="true">a </span>**<span color="blue" underline="true">c</span>**',
            id="colour-in-bold-inside-an-underline",
        ),
        pytest.param(
            parse_rich("++fill {{owner}}++"),
            '<span underline="true">fill </span>'
            '<span color="yellow_bg" underline="true">\\{\\{owner\\}\\}</span>',
            id="placeholder-inside-an-underline",
        ),
        pytest.param(
            parse_rich("[due {{date}} now]{bg=sky}"),
            '<span color="pink_bg">due </span><span color="yellow_bg">\\{\\{date\\}\\}</span>'
            '<span color="pink_bg"> now</span>',
            id="placeholder-inside-a-highlight",
        ),
        pytest.param(
            parse_rich("[ask {{owner}} first]{tone=danger}"),
            '<span color="red">ask </span><span color="yellow_bg">\\{\\{owner\\}\\}</span>'
            '<span color="red"> first</span>',
            id="placeholder-inside-a-colour",
        ),
        pytest.param(
            parse_rich("[++ask {{owner}}++ first]{tone=danger}"),
            '<span color="red" underline="true">ask </span>'
            '<span color="yellow_bg" underline="true">\\{\\{owner\\}\\}</span>'
            '<span color="red"> first</span>',
            id="placeholder-inside-an-underline-inside-a-colour",
        ),
        pytest.param(
            (TonedLabel("danger", (Plain("ask "), Placeholder("owner"))),),
            '<span color="red">ask </span><span color="yellow_bg">\\{\\{owner\\}\\}</span>',
            id="placeholder-inside-a-toned-label",
        ),
        pytest.param(
            (TonedLabel("danger", (Plain("Scan "), Styled("underline", (Plain("now"),)))),),
            '<span color="red">Scan </span><span color="red" underline="true">now</span>',
            id="underline-inside-a-toned-label",
        ),
    ],
)
def test_spans_of_different_attributes_are_written_side_by_side_each_carrying_every_enclosing_attribute(
    runs: ExportRich, notion: str
) -> None:
    assert notion_inline(runs) == notion


def test_an_underline_inside_a_colour_passes_the_notion_check_and_is_written_beside_it() -> None:
    blocks = [{"type": "text", "body": "Zone [a ++u++ b]{tone=danger}."}]

    assert render_export(parse_report(make_report(blocks=blocks)), "notion").pages == {
        "page.md": 'Zone <span color="red">a </span><span color="red" underline="true">u</span>'
        '<span color="red"> b</span>.\n'
    }


def test_a_colour_inside_a_colour_passes_the_notion_check_and_is_written_beside_it() -> None:
    blocks = [{"type": "text", "body": "Zone [a [x]{tone=info} b]{tone=danger}."}]

    assert render_export(parse_report(make_report(blocks=blocks)), "notion").pages == {
        "page.md": 'Zone <span color="red">a </span><span color="blue">x</span><span color="red"> b</span>.\n'
    }


def test_a_blank_in_a_colour_span_passes_the_notion_check_and_is_written_as_a_highlight_beside_it() -> None:
    blocks = [{"type": "text", "body": "Ask [the {{owner}} first]{tone=danger}."}]

    assert render_export(parse_report(make_report(blocks=blocks)), "notion").pages == {
        "page.md": 'Ask <span color="red">the </span><span color="yellow_bg">\\{\\{owner\\}\\}</span>'
        '<span color="red"> first</span>.\n'
    }


def test_a_blank_in_a_toned_step_title_is_written_on_notion_beside_the_step_colour() -> None:
    report = parse_report(make_report(blocks=toned_step_titled("ask {{owner}} first")))

    assert render_export(report, "notion").pages == {
        "page.md": '1. <span color="red">**Scan** </span>*<span color="red">ask </span>'
        '<span color="yellow_bg">\\{\\{owner\\}\\}</span><span color="red"> first</span>*\n\tBoth aisles.\n'
    }


@pytest.mark.parametrize(
    ("runs", "notion"),
    [
        pytest.param(
            (TonedLabel("danger", (Plain("run "), Code("</b>"), Plain(" first"))),),
            '<span color="red">run </span>`</b>`<span color="red"> first</span>',
            id="beside-the-text",
        ),
        pytest.param(
            (TonedLabel("danger", (Styled("italic", (Code("</b>"),)),)),),
            "*`</b>`*",
            id="alone-in-italic",
        ),
        pytest.param(
            (TonedLabel("danger", (Plain("see "), Code("List<int>"))),),
            '<span color="red">see `List<int>`</span>',
            id="code-without-a-closing-tag-stays-inside",
        ),
    ],
)
def test_code_holding_a_closing_tag_in_a_toned_label_is_written_outside_the_generated_span(
    runs: ExportRich, notion: str
) -> None:
    assert notion_inline(runs) == notion


def test_code_holding_a_closing_tag_in_a_toned_step_title_is_written_outside_the_step_colour() -> None:
    report = parse_report(make_report(blocks=toned_step_titled("run `</span>` first")))

    assert render_export(report, "notion").pages == {
        "page.md": '1. <span color="red">**Scan** </span>*<span color="red">run </span>`</span>`'
        '<span color="red"> first</span>*\n\tBoth aisles.\n'
    }


def test_code_holding_a_closing_tag_in_an_author_colour_in_a_toned_step_title_is_refused_for_notion() -> None:
    report = parse_report(make_report(blocks=toned_step_titled("run [`</span>`]{tone=info} first")))

    with pytest.raises(ExportRejectedError) as raised:
        render_export(report, "notion")

    assert vars(raised.value) == {
        "target": "notion",
        "why": "Notion closes a coloured, highlighted or underlined span early at inline code holding '</', "
        "as in '</span>'",
        "instead": "write the code outside the coloured, highlighted or underlined text, or without '</'",
        "where": "at blocks.0.walkthrough",
    }


def test_an_author_colour_in_a_toned_step_title_is_written_beside_the_step_colour() -> None:
    report = parse_report(make_report(blocks=toned_step_titled("the [cold room]{tone=info} first")))

    assert render_export(report, "notion").pages == {
        "page.md": '1. <span color="red">**Scan** </span>*<span color="red">the </span>'
        '<span color="blue">cold room</span><span color="red"> first</span>*\n\tBoth aisles.\n'
    }


@pytest.mark.parametrize(
    ("runs", "message"),
    [
        pytest.param(
            (Tinted("danger", None, (Tinted(None, "sky", (Plain("x"),)),)),),
            "Notion holds no span inside a span, so it cannot show a highlight inside a colour; "
            "the export check should have refused it",
            id="highlight-inside-a-colour",
        ),
        pytest.param(
            (Tinted(None, "sky", (Styled("bold", (Tinted("danger", None, (Plain("x"),)),)),)),),
            "Notion holds no span inside a span, so it cannot show a colour inside a highlight; "
            "the export check should have refused it",
            id="colour-inside-bold-inside-a-highlight",
        ),
        pytest.param(
            (TonedLabel("danger", (Tinted(None, "sky", (Plain("x"),)),)),),
            "Notion holds no span inside a span, so it cannot show a highlight inside a colour; "
            "the export check should have refused it",
            id="highlight-inside-a-toned-label",
        ),
        pytest.param(
            (Tinted("danger", None, (Plain("see "), Code("</span>"))),),
            "Notion closes a coloured, highlighted or underlined span early at inline code holding '</', "
            "'</span>'; the export check should have refused it",
            id="closing-tag-in-code-inside-a-colour",
        ),
        pytest.param(
            (TonedLabel("danger", (Styled("underline", (Code("</b>"),)),)),),
            "Notion closes a coloured, highlighted or underlined span early at inline code holding '</', "
            "'</b>'; the export check should have refused it",
            id="closing-tag-in-code-inside-an-underline-inside-a-toned-label",
        ),
        pytest.param(
            (TonedLabel("danger", (Tinted("info", None, (Code("</b>"),)),)),),
            "Notion closes a coloured, highlighted or underlined span early at inline code holding '</', "
            "'</b>'; the export check should have refused it",
            id="closing-tag-in-code-inside-a-colour-inside-a-toned-label",
        ),
        pytest.param(
            (Styled("underline", (Plain("see "), Code("</span>"))),),
            "Notion closes a coloured, highlighted or underlined span early at inline code holding '</', "
            "'</span>'; the export check should have refused it",
            id="closing-tag-in-code-inside-an-underline",
        ),
    ],
)
def test_the_notion_writer_refuses_a_span_nesting_the_check_refuses_as_an_invariant(
    runs: ExportRich, message: str
) -> None:
    with pytest.raises(ExportInvariantError) as raised:
        notion_inline(runs)

    assert str(raised.value) == message


@pytest.mark.parametrize(
    ("runs", "message"),
    [
        pytest.param(
            (Tinted("accent", "sky", (Plain("lots"),)),),
            "a Notion text run takes a colour or a highlight, not both; "
            "the export check should have refused it",
            id="colour-and-highlight",
        ),
        pytest.param(
            (DocumentLink((Plain("the plan"),), "cold-room-plan", None),),
            "this target cannot link to another skaldr document; the export check should have refused it",
            id="link-to-another-document",
        ),
        pytest.param(
            (AnchorLink((Plain("the counts"),), "counts"),),
            "a Notion page cannot link to its own headings; the export check should have refused it",
            id="link-to-a-heading-the-author-wrote",
        ),
    ],
)
def test_the_notion_writer_refuses_what_the_export_check_refuses_as_an_invariant(
    runs: ExportRich, message: str
) -> None:
    with pytest.raises(ExportInvariantError, match=f"^{re.escape(message)}$"):
        notion_inline(runs)


def test_emphasis_beside_a_notion_color_span_keeps_its_markers_because_the_span_tag_closes_it() -> None:
    body = "**(bold)**[t]{tone=danger} and [a]{tone=info}*(x)* y"

    assert notion_of([{"type": "text", "body": body}]) == (
        '**(bold)**<span color="red">t</span> and <span color="blue">a</span>*(x)* y\n'
    )


def test_a_notion_callout_with_an_empty_first_paragraph_keeps_its_list_a_list() -> None:
    callout = Callout("info", (Paragraph(()), ListNode("bullet", (ListEntry((Plain("first"),)),))))

    assert render_notion([callout]) == '<callout icon="💡" color="blue_bg">\n\t- first\n</callout>\n'


def test_inline_math_is_notion_inline_math_while_prose_dollars_stay_escaped() -> None:
    assert notion_inline(parse_rich("costs $5, so $`x_i < 2`$ holds")) == "costs \\$5, so $`x_i < 2`$ holds"


def test_a_math_block_is_a_notion_equation_block_indented_inside_a_callout() -> None:
    callout = {"type": "callout", "tone": "info", "body": "Rate"}
    math = {"type": "math", "expression": "a\n\n  b\n"}

    assert notion_of([math, {"type": "panel", "title": "P", "blocks": [callout, math]}]) == (
        "$$\na\n  b\n$$\n"
        '<callout icon="📝" color="gray_bg">\n\t**P**\n'
        '\t<callout icon="💡" color="blue_bg">\n\t\tRate\n\t</callout>\n'
        "\t$$\n\ta\n\t  b\n\t$$\n</callout>\n"
    )


def test_marker_characters_that_form_no_mark_stay_escaped_prose_in_notion() -> None:
    assert notion_inline(parse_rich("C++ in ~5 days, 2^10 and a ++ b ++ c")) == (
        "C++ in \\~5 days, 2\\^10 and a ++ b ++ c"
    )


def test_a_code_label_holding_a_backtick_is_refused_for_notion() -> None:
    report = parse_report(make_report(blocks=[{"type": "code", "label": "a`b", "content": "x"}]))

    with pytest.raises(ExportRejectedError) as raised:
        render_export(report, "notion")

    assert str(raised.value) == (
        "Notion cannot show inline code holding a backtick, as in 'a`b', at blocks.0.code; "
        "write the code in a code block, or without the backtick"
    )


def test_a_code_block_containing_a_fence_gets_a_longer_one() -> None:
    assert notion_of([{"type": "code", "content": "```\ninner\n```"}]) == (
        "````plain text\n```\ninner\n```\n````\n"
    )


@pytest.mark.parametrize(
    ("code", "fence"),
    [
        pytest.param(
            {"content": "x"}, "```plain text", id="no-language-is-plain-text-not-notions-javascript"
        ),
        pytest.param({"content": "x", "lang": "shell"}, "```shell", id="an-authored-language"),
        pytest.param({"label": "run.sh", "content": "x"}, "```bash", id="a-language-from-the-label"),
    ],
)
def test_a_notion_code_fence_always_names_a_language(code: dict[str, Any], fence: str) -> None:
    assert notion_of([{"type": "code", **code}]).splitlines()[-3] == fence


def test_a_code_fence_inside_a_callout_also_says_plain_text() -> None:
    grid = {
        "type": "grid",
        "cells": [{"span": 6, "tone": "info", "blocks": [{"type": "code", "content": "x"}]}],
    }

    assert (
        notion_of([grid]) == '<callout icon="💡" color="blue_bg">\n\t```plain text\n\tx\n\t```\n</callout>\n'
    )


def test_the_notion_footer_shows_rich_text_from_the_source_and_plain_facts() -> None:
    page = notion_of(
        [{"type": "text", "body": "x"}], meta={"title": "T", "source": "see `app.ts`", "date": "5 Oct"}
    )

    assert page.splitlines()[-1] == 'see `app.ts` · 5 Oct {color="gray"}'


@pytest.mark.parametrize(
    ("body", "line"),
    [
        pytest.param("- not a list", "\\- not a list", id="dash"),
        pytest.param("# not a heading", "\\# not a heading", id="hash"),
        pytest.param("1. not a list", "1\\. not a list", id="ordered"),
        pytest.param("--- not a rule", "\\--- not a rule", id="rule"),
        pytest.param("2024. was the year", "2024\\. was the year", id="year-ordinal"),
        pytest.param("123456789. x", "123456789\\. x", id="nine-digit-ordinal-is-a-list"),
    ],
)
def test_a_paragraph_that_starts_like_a_block_marker_stays_a_paragraph(body: str, line: str) -> None:
    assert notion_of([{"type": "text", "body": body}]) == f"{line}\n"


def test_list_entries_and_quote_lines_escape_a_leading_block_marker() -> None:
    blocks = [
        {"type": "list", "items": ["# not a heading"]},
        {"type": "quote", "body": "- not a list\n\n# nor a heading", "cite": "Ops"},
    ]

    assert notion_of(blocks) == "- \\# not a heading\n> \\- not a list<br>\\# nor a heading<br>*Ops*\n"


@pytest.mark.parametrize("tone", [pytest.param(tone, id=tone) for tone in get_args(BadgeColorLiteral)])
def test_every_badge_color_has_a_notion_chip_color(tone: BadgeColorLiteral) -> None:
    color = NOTION_CHIP_COLOR.get(tone)

    assert notion_inline((Chip("a*b", tone),)) == f'<span color="{color}">**a\\*b**</span>'


def test_no_two_badge_colors_share_a_notion_color() -> None:
    assert sorted(NOTION_CHIP_COLOR.values()) == sorted(set(NOTION_CHIP_COLOR.values()))


def test_a_chip_label_that_names_a_file_is_inline_code_so_notion_does_not_link_it() -> None:
    assert notion_inline((Chip("README.md", "blue"),)) == '<span color="blue">**`README.md`**</span>'


def test_a_toned_title_is_coloured_text_and_the_rest_of_the_line_stays_plain() -> None:
    entry = ListEntry((TonedLabel("info", (Styled("bold", (Plain("Go"),)),)), Plain(": now")))

    assert render_notion([ListNode("number", (entry,))]) == '1. <span color="blue">**Go**</span>: now\n'


def test_every_badge_and_state_block_becomes_notion_markdown() -> None:
    assert notion_of(BADGE_AND_STATE_BLOCKS, badges=API_BADGES) == (
        "<details>\n<summary>Legend: badges used on this page</summary>\n"
        '\t- <span color="blue">**api**</span> the API\n</details>\n'
        "<columns>\n"
        '\t<column ratio="50">\n\t\tSite {color="gray"}\n\t\tWest\n\t</column>\n'
        '\t<column ratio="50">\n\t\tOwner {color="gray"}\n\t\tops\n\t</column>\n'
        "</columns>\n"
        '<table fit-page-width="true" header-column="true">\n'
        "\t<tr>\n\t\t<td>**Lead**</td>\n\t\t<td>**Ana**</td>\n\t</tr>\n"
        "</table>\n"
        "**Drift**\n\tfirst\n\tsecond\n**Gap**\n"
        "<columns>\n"
        '\t<column ratio="50">\n'
        '\t\t<callout icon="📝" color="gray_bg">\n'
        "\t\t\t**Clean**\n"
        '\t\t\t9 (90.0%) <span color="green">**▲ +1**</span> <span color="blue">**api**</span>\n'
        '\t\t\tsince Monday {color="gray"}\n'
        "\t\t</callout>\n"
        "\t</column>\n"
        '\t<column ratio="50">\n'
        '\t\t<callout icon="📝" color="gray_bg">\n'
        "\t\t\t**Lag**\n\t\t\t3 days → flat\n"
        "\t\t</callout>\n"
        "\t</column>\n"
        "</columns>\n"
        '**Affects**: <span color="blue">**api**</span> <span color="brown">**ops**</span>\n'
        '- **Owners**: <span color="purple">**web**</span>\n<empty-block/>\n'
        '- <span color="green">✓</span> Ship\n- <span color="yellow">⏸</span> Vendor\n<empty-block/>\n'
        '- <span color="blue">◐</span> **Mon**: Start <span color="blue">**api**</span>\n'
        "\tkick-off\n- Later\n<empty-block/>\n"
        '- <span color="yellow">**Zone**</span>: ████░░░░░░ 42.9%\n'
    )


def test_the_notion_legend_is_a_toggle_of_colored_chips_before_the_content() -> None:
    row = {"type": "badge_row", "items": [{"key": "API"}]}

    assert notion_of([row], badges=API_BADGES) == (
        "<details>\n<summary>Legend: badges used on this page</summary>\n"
        '\t- <span color="blue">**api**</span> the API\n</details>\n'
        '<span color="blue">**api**</span>\n'
    )


def test_a_toggle_is_a_details_block_with_its_content_tab_indented_at_every_depth() -> None:
    inner = {"type": "toggle", "title": "Inner", "blocks": [{"type": "text", "body": "y"}]}
    toggle = {"type": "toggle", "title": "Raw counts", "blocks": [{"type": "text", "body": "x"}, inner]}

    assert notion_of([toggle]) == (
        "<details>\n<summary>Raw counts</summary>\n\tx\n"
        "\t<details>\n\t<summary>Inner</summary>\n\t\ty\n\t</details>\n</details>\n"
    )


def test_an_open_toggle_is_its_bold_title_over_its_content_rather_than_a_details_block() -> None:
    toggle = make_toggle({"type": "text", "body": "x"}, title="Raw counts", collapsed=False)

    assert notion_of([toggle]) == "**Raw counts**\nx\n"


def test_authored_tabs_are_native_tabs_with_the_tone_icon() -> None:
    block = {
        "type": "tabs",
        "tabs": [
            {"label": "Floor", "tone": "warning", "blocks": [{"type": "text", "body": "a"}]},
            {"label": "System", "tone": "accent", "blocks": [{"type": "text", "body": "b"}]},
            {"label": "Vendor", "blocks": [{"type": "divider"}]},
        ],
    }

    assert notion_of([block]) == (
        "<tabs>\n"
        '\t<tab icon="⚠️">\n\t\tFloor\n\t\ta\n\t</tab>\n'
        "\t<tab>\n\t\tSystem\n\t\tb\n\t</tab>\n"
        "\t<tab>\n\t\tVendor\n\t\t---\n\t</tab>\n"
        "</tabs>\n"
    )


def test_a_level_four_heading_is_four_hashes() -> None:
    assert notion_of([{"type": "heading", "level": 4, "text": "Bin detail"}]) == "#### Bin detail\n"


def _appendix_with_zone_and_bin_headings(*, collapsed: bool) -> dict[str, Any]:
    return {
        "type": "section",
        "title": "Appendix",
        "collapsed": collapsed,
        "blocks": [
            {"type": "heading", "level": 3, "text": "Zone C"},
            {"type": "heading", "level": 4, "text": "Bin 12"},
        ],
    }


def test_a_level_3_and_a_level_4_heading_in_a_section_stay_apart_after_the_shift() -> None:
    section = _appendix_with_zone_and_bin_headings(collapsed=False)

    assert notion_of([section]) == "# Appendix\n### Zone C\n#### Bin 12\n"


def test_a_collapsed_sections_toggle_heading_moves_up_with_the_headings_inside_it() -> None:
    section = _appendix_with_zone_and_bin_headings(collapsed=True)

    assert notion_of([section]) == '# Appendix {toggle="true"}\n\t### Zone C\n\t#### Bin 12\n'


def test_a_document_that_goes_no_deeper_than_heading_4_keeps_its_levels() -> None:
    section = {
        "type": "section",
        "title": "Appendix",
        "collapsed": False,
        "blocks": [{"type": "heading", "level": 3, "text": "Zone C"}],
    }

    assert notion_of([section]) == "## Appendix\n#### Zone C\n"


def test_a_deep_heading_nested_in_a_callout_moves_the_whole_document_up_one_level() -> None:
    nodes = [
        Heading(2, (Plain("Top"),)),
        Heading(3, (Plain("Mid"),)),
        Callout("info", (Heading(5, (Plain("Deep"),)),)),
    ]

    assert render_notion(nodes) == (
        '# Top\n## Mid\n<callout icon="💡" color="blue_bg">\n\t#### Deep\n</callout>\n'
    )


def test_an_index_with_parts_has_no_level_1_to_spare_and_keeps_clamping_at_heading_4() -> None:
    nodes = [
        Heading(1, (Plain("Part"),)),
        Heading(2, (Plain("Section"),)),
        Heading(4, (Plain("Four"),)),
        Heading(5, (Plain("Five"),)),
    ]

    assert render_notion(nodes) == "# Part\n## Section\n#### Four\n#### Five\n"


def test_a_collapsed_part_is_a_level_1_heading_so_the_clamp_stays() -> None:
    part = Toggle((Plain("Part"),), 1, (Heading(2, (Plain("Section"),)), Heading(5, (Plain("Five"),))))

    assert render_notion([part]) == '# Part {toggle="true"}\n\t## Section\n\t#### Five\n'


def test_a_toggle_heading_deeper_than_heading_4_is_the_only_trigger_for_the_shift() -> None:
    nodes = [
        Heading(2, (Plain("Top"),)),
        Toggle((Plain("Deep"),), 5, (Paragraph((Plain("inside"),)),)),
    ]

    assert render_notion(nodes) == '# Top\n#### Deep {toggle="true"}\n\tinside\n'


def _in_a_tab(deep: Heading) -> Node:
    return Tabs((Tab((Plain("T"),), (deep,)),))


def _in_a_column(deep: Heading) -> Node:
    return Columns((GridColumn(1, (deep,)),))


def _in_a_list_item(deep: Heading) -> Node:
    return ListNode("bullet", (ListEntry((Plain("item"),), children=(deep,)),))


@pytest.mark.parametrize(
    "container",
    [
        pytest.param(_in_a_tab, id="tab"),
        pytest.param(_in_a_column, id="column"),
        pytest.param(_in_a_list_item, id="list-item"),
    ],
)
def test_a_deep_heading_in_a_nested_container_moves_the_heading_before_it_up_one_level(
    container: Callable[[Heading], Node],
) -> None:
    nodes = [Heading(2, (Plain("Top"),)), container(Heading(5, (Plain("Deep"),)))]

    written = render_notion(nodes).splitlines()

    assert [line.strip() for line in written if "Top" in line or "Deep" in line] == ["# Top", "#### Deep"]


@pytest.mark.parametrize(
    ("level", "line"),
    [
        pytest.param(4, "#### Deep", id="heading-4"),
        pytest.param(5, "#### Deep", id="heading-5"),
        pytest.param(6, "#### Deep", id="heading-6"),
    ],
)
def test_a_heading_node_past_level_four_is_written_at_the_deepest_level_notion_takes(
    level: HeadingLevel, line: str
) -> None:
    assert render_notion([Heading(level, (Plain("Deep"),))]) == f"{line}\n"


def test_a_divider_is_a_notion_divider_line_between_its_neighbours() -> None:
    blocks = [{"type": "text", "body": "Above"}, {"type": "divider"}, {"type": "text", "body": "Below"}]

    assert notion_of(blocks) == "Above\n---\nBelow\n"


@pytest.mark.parametrize(
    ("image", "line"),
    [
        pytest.param(
            {"caption": "Overflow bins"},
            "![Overflow bins](https://example.com/aisle.png)",
            id="the-caption-is-the-notion-caption",
        ),
        pytest.param({}, "![Aisle 12](https://example.com/aisle.png)", id="alt-stands-in-without-a-caption"),
    ],
)
def test_a_web_image_is_a_notion_image_line(image: dict[str, Any], line: str) -> None:
    block = {"type": "image", "src": "https://example.com/aisle.png", "alt": "Aisle 12", **image}

    assert notion_of([block]) == f"{line}\n"


@pytest.mark.parametrize("kind", ["video", "audio", "file", "pdf"])
def test_a_media_block_is_a_notion_tag_holding_its_caption(kind: str) -> None:
    block = {"type": "media", "kind": kind, "src": "https://example.com/a?x=1&y=2", "caption": "Dock walk"}

    assert notion_of([block]) == f'<{kind} src="https://example.com/a?x=1&y=2">Dock walk</{kind}>\n'


def test_a_media_url_is_percent_encoded_in_the_notion_src_so_it_cannot_close_the_attribute() -> None:
    src = "https://example.com/a(1)?x=\"1\"&y=<2>&z='3'"
    block = {"type": "media", "kind": "video", "src": src}

    assert notion_of([block]) == (
        "<video src=\"https://example.com/a%281%29?x=%221%22&y=%3C2%3E&z='3'\"></video>\n"
    )


def test_a_notion_media_caption_cannot_close_the_tag_or_open_another() -> None:
    block = {
        "type": "media",
        "kind": "video",
        "src": "https://example.com/walk.mp4",
        "caption": "a </video> b <i>",
    }

    assert (
        notion_of([block]) == '<video src="https://example.com/walk.mp4">a \\</video\\> b \\<i\\></video>\n'
    )


@pytest.mark.parametrize(
    ("container", "heading"),
    [
        pytest.param(in_an_open_section, "## part\n", id="section"),
        pytest.param(in_a_grid_cell, "", id="grid"),
    ],
)
def test_a_web_image_and_a_media_block_nest_in_a_section_or_a_grid_cell(
    container: Callable[[list[dict[str, Any]]], dict[str, Any]], heading: str
) -> None:
    blocks = [
        {"type": "image", "src": "https://example.com/a.png", "alt": "A", "caption": "Cap"},
        {"type": "media", "kind": "pdf", "src": "https://example.com/s.pdf", "caption": "Sheet"},
    ]

    assert notion_of([container(blocks)]) == (
        f'{heading}![Cap](https://example.com/a.png)\n<pdf src="https://example.com/s.pdf">Sheet</pdf>\n'
    )


def test_a_media_block_without_a_caption_is_an_empty_notion_tag() -> None:
    block = {"type": "media", "kind": "pdf", "src": "https://example.com/sheet.pdf"}

    assert notion_of([block]) == '<pdf src="https://example.com/sheet.pdf"></pdf>\n'


def test_block_nodes_become_notion_blocks() -> None:
    nodes = [
        Paragraph((Plain("muted"),), "muted"),
        ListNode("number", (ListEntry((Plain("one"),)),)),
        ListNode("check", (ListEntry((Plain("done"),), checked=True), ListEntry((Plain("open"),)))),
        Callout("info", (Paragraph((Plain("tip"),)),)),
        Quote((Paragraph((Plain("said"),)),)),
        Toggle((Plain("Legend"),), None, (Paragraph((Plain("x"),)),)),
        Toggle((Plain("Shut"),), 2, (Paragraph((Plain("y"),)),)),
        Tabs((Tab((Plain("plain"),), (Paragraph((Plain("z"),)),)),)),
        Diagram(Graph("LR", (GraphNode("s1", "A"),), (), "flow"), (Paragraph((Plain("detail"),)),)),
    ]

    assert render_notion(nodes) == (
        'muted {color="gray"}\n'
        "1. one\n"
        "- [x] done\n"
        "- [ ] open\n"
        '<callout icon="💡" color="blue_bg">\n\ttip\n</callout>\n'
        "> said\n"
        "<details>\n<summary>Legend</summary>\n\tx\n</details>\n"
        '## Shut {toggle="true"}\n\ty\n'
        "<tabs>\n\t<tab>\n\t\tplain\n\t\tz\n\t</tab>\n</tabs>\n"
        '```mermaid\nflowchart LR\n    s1["A"]\n```\ndetail\n'
    )


def _block_types_in(blocks: Sequence[AnyBlock]) -> set[str]:
    return {block.type for block in walk_blocks(blocks)}


def test_the_export_fixture_uses_every_block_type() -> None:
    assert _block_types_in(load_report(EXAMPLE).blocks) == authored_block_types()


def test_the_example_is_refused_for_notion_at_its_first_refusal_in_document_order(tmp_path: Path) -> None:
    with pytest.raises(ExportRejectedError) as raised:
        export_notion(load_report(EXAMPLE), tmp_path)

    assert str(raised.value) == FIRST_REFUSAL_IN_DOCUMENT_ORDER_OF_THE_EXAMPLE["notion"]


def test_the_example_reworked_for_notion_less_the_blocks_notion_refuses_matches_the_notion_golden(
    tmp_path: Path,
) -> None:
    out_dir = golden_or_scratch_folder("notion", tmp_path)

    export_notion(accepted_example("notion"), out_dir)

    assert (refused_block_types(example_for("notion"), "notion"), folder_texts(out_dir)) == (
        REFUSED_IN_THE_EXAMPLE["notion"],
        folder_texts(golden_of("notion")),
    )


def test_a_flow_becomes_a_mermaid_diagram_with_readable_labels() -> None:
    flow = {
        "type": "flow",
        "numbered": False,
        "steps": [{"label": "Scan", "tone": "info"}, {"label": 'Say "hi"', "note": "then **stop**"}],
    }

    assert notion_of([flow]) == (
        "```mermaid\n"
        "flowchart LR\n"
        '    s1["Scan"]:::info\n'
        '    s2["Say #quot;hi#quot;<br>then stop"]\n'
        "    s1 --> s2\n"
        "    classDef info fill:#eff6ff,stroke:#1d4ed8,color:#1f2328\n"
        "```\n"
    )


def test_a_single_series_line_chart_is_an_xy_chart_in_the_series_colour_of_the_page() -> None:
    line = {
        "type": "chart",
        "variant": "line",
        "categories": ["Q1", "Q2"],
        "series": [{"label": "x", "tone": "danger", "values": [1, 2]}],
    }

    assert notion_of([line]) == (
        '```mermaid\n%%{init: {"theme": "base", '
        '"themeVariables": {"xyChart": {"plotColorPalette": "#b91c1c"}}}}%%\n'
        'xychart-beta\n    x-axis ["Q1", "Q2"]\n    line [1, 2]\n```\n'
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**Series**</td>\n\t\t<td>**Q1**</td>\n\t\t<td>**Q2**</td>\n\t</tr>\n"
        '\t<tr>\n\t\t<td color="red_bg">x</td>\n\t\t<td>1</td>\n\t\t<td>2</td>\n\t</tr>\n'
        "</table>\n"
    )


def test_a_toned_donut_is_a_pie_in_the_slice_colours_of_the_page() -> None:
    donut = {
        "type": "chart",
        "variant": "donut",
        "slices": [{"label": "A", "value": 3, "tone": "success"}, {"label": "B", "value": 1}],
    }

    assert notion_of([donut]) == (
        '```mermaid\n%%{init: {"theme": "base", '
        '"themeVariables": {"pie1": "#15803d", "pie2": "#15803d", ' + PIE_TEXT_VARIABLES_JSON + "}}}%%\n"
        'pie\n    "A" : 3\n    "B" : 1\n```\n'
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**Slice**</td>\n\t\t<td>**Value**</td>\n\t\t<td>**Share**</td>\n\t</tr>\n"
        '\t<tr>\n\t\t<td color="green_bg">A</td>\n\t\t<td>3</td>\n\t\t<td>75%</td>\n\t</tr>\n'
        "\t<tr>\n\t\t<td>B</td>\n\t\t<td>1</td>\n\t\t<td>25%</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Total**</td>\n\t\t<td>**4**</td>\n\t\t<td></td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_matrix_cell_with_a_badge_and_a_label_shows_the_badge_name_in_bold_then_the_label() -> None:
    assert notion_of([MATRIX_OF_EVERY_CELL_SHAPE], badges=HAVE_BADGE) == (
        '<table fit-page-width="true" header-row="true" header-column="true">\n'
        "\t<tr>\n\t\t<td></td>\n\t\t<td>**Badge**</td>\n\t\t<td>**Both**</td>\n\t\t<td>**Tone**</td>\n"
        "\t\t<td>**Label**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Receiving**</td>\n"
        '\t\t<td color="green_bg">Have</td>\n'
        '\t\t<td color="green_bg">**Have** · runbook v2</td>\n'
        '\t\t<td color="red_bg">none yet</td>\n'
        "\t\t<td>n/a</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_matrix_cell_names_no_state_the_badge_label_does_not_add_and_escapes_the_ones_it_does() -> None:
    assert notion_of([MATRIX_OF_EDGE_BADGE_LABELS], badges=EDGE_BADGES) == (
        '<table fit-page-width="true" header-row="true" header-column="true">\n'
        "\t<tr>\n\t\t<td></td>\n\t\t<td>**Blank**</td>\n\t\t<td>**Spaces**</td>\n\t\t<td>**Same**</td>\n"
        "\t\t<td>**Special**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Receiving**</td>\n"
        '\t\t<td color="red_bg">lbl</td>\n'
        '\t\t<td color="yellow_bg">lbl</td>\n'
        '\t\t<td color="green_bg">Have</td>\n'
        '\t\t<td color="blue_bg">**A\\|B \\*x\\*** · a\\_b \\[c\\] \\<d\\> \\| e</td>\n'
        "\t</tr>\n"
        "</table>\n"
    )


def test_a_request_with_several_cases_is_native_tabs_with_the_status_icon() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "[]"}},
        {"label": "control", "tone": "info", "response": {"body": "none"}},
    ]
    request = make_command_request(cases=cases, command="list-tiers")

    assert notion_of([request]) == (
        "**Tier mappings on the partner API**\n"
        "<tabs>\n"
        '\t<tab icon="⚠️">\n'
        "\t\tfinding\n"
        "\t\t```bash\n\t\tlist-tiers\n\t\t```\n"
        "\t\t**Recorded output**\n"
        "\t\t```json\n\t\t[]\n\t\t```\n"
        "\t</tab>\n"
        '\t<tab icon="💡">\n'
        "\t\tcontrol\n"
        "\t\t```bash\n\t\tlist-tiers\n\t\t```\n"
        "\t\t**Recorded output**\n"
        "\t\t```plain text\n\t\tnone\n\t\t```\n"
        "\t</tab>\n"
        "</tabs>\n"
    )


def test_a_query_request_becomes_a_notion_code_block_in_its_language_labelled_with_the_runner() -> None:
    query = {"runner": "psql, reporting replica", "lang": "sql", "content": "SELECT 1"}

    assert notion_of([make_query_request(query=query)]) == (
        "**Open orders in the shop database**\n"
        "*open orders*\n"
        "**Query**: psql, reporting replica\n"
        "```sql\nSELECT 1\n```\n"
        "**Recorded output**\n"
        '```json\n[\n  {\n    "n": 12\n  }\n]\n```\n'
    )


@pytest.mark.parametrize(
    ("tone", "opening"),
    [
        pytest.param("success", '<tab icon="✅">', id="success"),
        pytest.param("info", '<tab icon="💡">', id="info"),
        pytest.param("warning", '<tab icon="⚠️">', id="warning"),
        pytest.param("danger", '<tab icon="🛑">', id="danger"),
        pytest.param("neutral", "<tab>", id="neutral-has-no-icon"),
        pytest.param(None, "<tab>", id="no-tone"),
    ],
)
def test_a_tab_icon_is_the_icon_of_its_tone(tone: ToneName | None, opening: str) -> None:
    tabs = Tabs((Tab((Plain("t"),), (Paragraph((Plain("z"),)),), tone),))

    assert render_notion([tabs]) == f"<tabs>\n\t{opening}\n\t\tt\n\t\tz\n\t</tab>\n</tabs>\n"


def test_a_tab_title_keeps_its_inline_styling_and_escapes_markup_characters() -> None:
    tabs = Tabs((Tab((Styled("bold", (Plain("a < b"),)),), (Paragraph((Plain("z"),)),)),))

    assert render_notion([tabs]) == "<tabs>\n\t<tab>\n\t\t**a \\< b**\n\t\tz\n\t</tab>\n</tabs>\n"


@pytest.mark.parametrize(
    ("title", "written"),
    [
        pytest.param("- a", "\\- a", id="bullet"),
        pytest.param("# a", "\\# a", id="heading"),
        pytest.param("1. a", "1\\. a", id="number"),
        pytest.param("> a", "\\> a", id="quote"),
    ],
)
def test_a_tab_title_that_looks_like_a_block_start_is_escaped(title: str, written: str) -> None:
    tabs = Tabs((Tab((Plain(title),), (Paragraph((Plain("z"),)),)),))

    assert render_notion([tabs]) == f"<tabs>\n\t<tab>\n\t\t{written}\n\t\tz\n\t</tab>\n</tabs>\n"


def test_a_tab_without_a_title_is_an_export_invariant_error() -> None:
    tabs = Tabs((Tab((), (Paragraph((Plain("z"),)),)),))

    with pytest.raises(ExportInvariantError) as raised:
        render_notion([tabs])

    assert str(raised.value) == (
        "a Notion tab needs a title, since Notion reads the first line of a tab as its title; "
        "the export check should have refused it"
    )


def test_a_tab_title_styled_beyond_bold_keeps_its_styling() -> None:
    title = (Styled("italic", (Plain("a"),)), Plain(" "), Styled("underline", (Plain("b"),)))
    tabs = Tabs((Tab(title, (Paragraph((Plain("z"),)),)),))

    assert render_notion([tabs]) == f"<tabs>\n\t<tab>\n\t\t{notion_inline(title)}\n\t\tz\n\t</tab>\n</tabs>\n"


def test_a_tab_nested_in_a_tab_nests_one_tab_stop_deeper() -> None:
    inner = Tabs((Tab((Plain("in"),), (Paragraph((Plain("z"),)),)),))
    outer = Tabs((Tab((Plain("out"),), (inner,)),))

    assert render_notion([outer]) == (
        "<tabs>\n\t<tab>\n\t\tout\n\t\t<tabs>\n\t\t\t<tab>\n\t\t\t\tin\n\t\t\t\tz\n\t\t\t</tab>\n\t\t</tabs>\n"
        "\t</tab>\n</tabs>\n"
    )


def test_tabs_inside_a_callout_nest_inside_the_callout() -> None:
    tabs = Tabs((Tab((Plain("t"),), (Paragraph((Plain("z"),)),)),))

    assert render_notion([Callout("info", (tabs,))]) == (
        '<callout icon="💡" color="blue_bg">\n\t<tabs>\n\t\t<tab>\n\t\t\tt\n\t\t\tz\n\t\t</tab>\n\t</tabs>\n'
        "</callout>\n"
    )


def test_tabs_inside_a_column_nest_inside_the_column() -> None:
    tabs = Tabs((Tab((Plain("t"),), (Paragraph((Plain("z"),)),)),))
    columns = Columns((GridColumn(1, (tabs,)),))

    assert render_notion([columns]) == (
        '<columns>\n\t<column ratio="1">\n'
        "\t\t<tabs>\n\t\t\t<tab>\n\t\t\t\tt\n\t\t\t\tz\n\t\t\t</tab>\n\t\t</tabs>\n"
        "\t</column>\n</columns>\n"
    )


def test_tabs_inside_a_toggle_nest_one_tab_stop_deeper_than_the_toggle_content() -> None:
    tabs = Tabs((Tab((Plain("t"),), (Paragraph((Plain("z"),)),)),))
    toggle = Toggle((Plain("More"),), None, (tabs,))

    assert render_notion([toggle]) == (
        "<details>\n<summary>More</summary>\n\t<tabs>\n\t\t<tab>\n\t\t\tt\n\t\t\tz\n\t\t</tab>\n\t</tabs>\n</details>\n"
    )


def test_a_diagram_with_nothing_beside_it_is_its_fence_alone() -> None:
    diagram = Diagram(Graph("LR", (GraphNode("s1", "A"),), (), "flow"))

    assert render_notion([diagram, Paragraph((Plain("after"),))]) == (
        '```mermaid\nflowchart LR\n    s1["A"]\n```\nafter\n'
    )


def test_a_page_with_a_table_of_contents_uses_the_notion_block() -> None:
    assert (
        notion_of([{"type": "heading", "text": "A"}], meta={"title": "T", "toc": True})
        == "<table_of_contents/>\n## A\n"
    )


def test_a_table_cell_of_code_plus_text_stays_a_cell_not_a_bullet() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}, {"key": "c", "label": "C"}],
        "rows": [{"a": "`flag` + default", "b": "- leading dash", "c": "1 + 1 and a+b"}],
    }

    assert notion_of([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**A**</td>\n\t\t<td>**B**</td>\n\t\t<td>**C**</td>\n\t</tr>\n"
        "\t<tr>\n"
        "\t\t<td>`flag` \N{FULLWIDTH PLUS SIGN} default</td>\n"
        "\t\t<td>\\- leading dash</td>\n"
        "\t\t<td>1 + 1 and a+b</td>\n"
        "\t</tr>\n"
        "</table>\n"
    )


@pytest.mark.parametrize(
    ("columns", "colgroup"),
    [
        pytest.param(
            [
                {"key": "a", "label": "A", "width": 1},
                {"key": "b", "label": "B", "tone": "success", "width": 2},
                {"key": "c", "label": "C", "width": 3},
            ],
            '\t<colgroup>\n\t\t<col width="118">\n\t\t<col color="green_bg" width="236">\n'
            '\t\t<col width="354">\n\t</colgroup>\n',
            id="widths-in-the-html-ratio-and-a-tone",
        ),
        pytest.param(
            [
                {"key": "a", "label": "A", "width": 1},
                {"key": "b", "label": "B", "width": 1},
                {"key": "c", "label": "C", "width": 1},
            ],
            '\t<colgroup>\n\t\t<col width="236">\n\t\t<col width="236">\n'
            '\t\t<col width="236">\n\t</colgroup>\n',
            id="equal-thirds-sum-to-the-page-width",
        ),
        pytest.param(
            [
                {"key": "a", "label": "A", "width": 6},
                {"key": "b", "label": "B", "width": 1},
                {"key": "c", "label": "C", "width": 1},
            ],
            '\t<colgroup>\n\t\t<col width="531">\n\t\t<col width="89">\n'
            '\t\t<col width="88">\n\t</colgroup>\n',
            id="the-leftover-pixel-goes-to-the-first-largest-remainder",
        ),
        pytest.param(
            [
                {"key": "a", "label": "A", "width": 1},
                {"key": "b", "label": "B", "width": 3},
                {"key": "c", "label": "C", "width": 3},
            ],
            '\t<colgroup>\n\t\t<col width="101">\n\t\t<col width="304">\n'
            '\t\t<col width="303">\n\t</colgroup>\n',
            id="quotas-rounding-each-to-707-gain-the-missing-pixel",
        ),
        pytest.param(
            [
                {"key": "a", "label": "A", "width": 1},
                {"key": "b", "label": "B", "width": 1},
                {"key": "c", "label": "C", "width": 3},
            ],
            '\t<colgroup>\n\t\t<col width="142">\n\t\t<col width="141">\n'
            '\t\t<col width="425">\n\t</colgroup>\n',
            id="quotas-rounding-each-to-709-lose-the-extra-pixel",
        ),
        pytest.param(
            [
                {"key": "a", "label": "A"},
                {"key": "b", "label": "B", "tone": "danger"},
                {"key": "c", "label": "C"},
            ],
            '\t<colgroup>\n\t\t<col>\n\t\t<col color="red_bg">\n\t\t<col>\n\t</colgroup>\n',
            id="a-tone-alone",
        ),
        pytest.param(
            [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}, {"key": "c", "label": "C"}],
            "",
            id="no-colgroup-without-a-tone-or-width",
        ),
    ],
)
def test_column_tones_and_widths_become_a_notion_colgroup(
    columns: list[dict[str, object]], colgroup: str
) -> None:
    table = make_table(columns, rows=[{"a": "x", "b": "y", "c": "z"}])

    assert notion_of([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        f"{colgroup}"
        "\t<tr>\n\t\t<td>**A**</td>\n\t\t<td>**B**</td>\n\t\t<td>**C**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>x</td>\n\t\t<td>y</td>\n\t\t<td>z</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_code_holding_an_angle_bracket_in_a_table_cell_stays_code() -> None:
    table = make_table([{"key": "a", "label": "A"}], rows=[{"a": "a `List<int>` type"}])

    assert notion_of([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**A**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>a `List<int>` type</td>\n\t</tr>\n"
        "</table>\n"
    )


@pytest.mark.parametrize(
    ("text", "notion"),
    [
        pytest.param("inline `</callout>` code", "inline `</callout>` code", id="a-closing-tag"),
        pytest.param("a `List<int>` type", "a `List<int>` type", id="an-angle-bracket"),
        pytest.param("a `<br>` tag", "a `<br>` tag", id="an-opening-tag"),
        pytest.param("a `x > 1` test", "a `x > 1` test", id="a-closing-angle-bracket"),
    ],
)
def test_code_holding_an_angle_bracket_or_a_closing_tag_outside_a_table_stays_code(
    text: str, notion: str
) -> None:
    assert notion_inline(parse_rich(text)) == notion


def test_the_notion_writer_refuses_code_holding_a_backtick_as_an_invariant() -> None:
    with pytest.raises(ExportInvariantError) as raised:
        notion_inline((Code("a`b"),))

    assert str(raised.value) == (
        "Notion cannot show inline code holding a backtick, 'a`b'; the export check should have refused it"
    )


def test_the_notion_writer_refuses_code_holding_a_closing_tag_in_a_table_cell_as_an_invariant() -> None:
    table = TableNode((TableCell((Code("</td>"),)),), ())

    with pytest.raises(ExportInvariantError) as raised:
        render_notion([table])

    assert str(raised.value) == (
        "Notion loses a table cell whose inline code holds '</', '</td>'; "
        "the export check should have refused it"
    )


def test_a_single_weighted_column_takes_the_whole_page_width() -> None:
    table = make_table([{"key": "a", "label": "A", "width": 3}], rows=[{"a": "x"}])

    assert notion_of([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        '\t<colgroup>\n\t\t<col width="708">\n\t</colgroup>\n'
        "\t<tr>\n\t\t<td>**A**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>x</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_auto_columns_share_what_a_number_column_default_width_leaves() -> None:
    table = make_table(
        [
            {"key": "a", "label": "A"},
            {"key": "b", "label": "B"},
            {"key": "c", "label": "C", "kind": "number"},
        ],
        rows=[{"a": "x", "b": "y", "c": 10}],
    )

    assert notion_of([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        '\t<colgroup>\n\t\t<col width="319">\n\t\t<col width="318">\n\t\t<col width="71">\n\t</colgroup>\n'
        "\t<tr>\n\t\t<td>**A**</td>\n\t\t<td>**B**</td>\n\t\t<td>**C**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>x</td>\n\t\t<td>y</td>\n\t\t<td>10</td>\n\t</tr>\n"
        "</table>\n"
    )


@pytest.mark.parametrize(
    ("count", "widths"),
    [
        pytest.param(9, [71] * 8 + [70] * 2, id="nine-numbers-share-tenths-with-the-label"),
        pytest.param(10, [65] * 4 + [64] * 7, id="ten-numbers-share-elevenths-with-the-label"),
        pytest.param(12, [55] * 6 + [54] * 7, id="twelve-numbers-share-thirteenths-with-the-label"),
    ],
)
def test_number_columns_too_many_for_their_default_width_leave_the_label_a_positive_width(
    count: int, widths: list[int]
) -> None:
    notion = notion_of([make_label_table(["number"] * count)])

    cols = "".join(f'\t\t<col width="{width}">\n' for width in widths)
    header = "".join(f"\t\t<td>**C{index}**</td>\n" for index in range(count))
    cells = "\t\t<td>1</td>\n" * count
    assert notion == (
        '<table fit-page-width="true" header-row="true">\n'
        f"\t<colgroup>\n{cols}\t</colgroup>\n"
        f"\t<tr>\n\t\t<td>**Label**</td>\n{header}\t</tr>\n"
        f"\t<tr>\n\t\t<td>x</td>\n{cells}\t</tr>\n"
        "</table>\n"
    )
    assert sum(widths) == NOTION_DEFAULT_PAGE_WIDTH_PX


@pytest.mark.parametrize(
    "shares",
    [
        pytest.param([0.1] * 10, id="written-as-tenths"),
        pytest.param([1 - 0.1 * 9, *[0.1] * 9], id="first-share-carries-float-noise"),
        pytest.param([*[0.1] * 9, 1 - 0.1 * 9], id="last-share-carries-float-noise"),
    ],
)
def test_equal_shares_apportion_the_same_pixels_in_column_order_whatever_their_float_noise(
    shares: list[float],
) -> None:
    assert apportioned(shares, NOTION_DEFAULT_PAGE_WIDTH_PX) == [71] * 8 + [70] * 2


def test_cell_tones_become_backgrounds_a_group_row_is_a_band_and_a_total_row_is_bold() -> None:
    table = TableNode(
        (TableCell((Plain("Name"),)), TableCell(())),
        (
            TableRow((TableCell((Plain("group"),)), TableCell(())), emphasis="group"),
            TableRow((TableCell((Plain("x"),), "danger"), TableCell((Plain("y"),), "teal"))),
            TableRow((TableCell((Plain("9"),)), TableCell(())), emphasis="total"),
        ),
        header_column=True,
    )

    assert render_notion([table]) == (
        '<table fit-page-width="true" header-row="true" header-column="true">\n'
        "\t<tr>\n\t\t<td>**Name**</td>\n\t\t<td></td>\n\t</tr>\n"
        '\t<tr color="gray_bg">\n\t\t<td>**group**</td>\n\t\t<td></td>\n\t</tr>\n'
        "\t<tr>\n"
        '\t\t<td color="red_bg">**x**</td>\n\t\t<td color="brown_bg">y</td>\n'
        "\t</tr>\n"
        "\t<tr>\n\t\t<td>**9**</td>\n\t\t<td></td>\n\t</tr>\n"
        "</table>\n"
    )


@pytest.mark.parametrize(
    ("cells", "lines"),
    [
        pytest.param(
            (TableCell((Plain("a"),)), TableCell((Plain("b "), Chip("New", "violet")))),
            ["<td>a</td>", '<td color="blue_bg">b **New**</td>'],
            id="the-cell-holding-the-badge-and-its-badge-in-the-normal-colour",
        ),
        pytest.param(
            (TableCell((Plain("a"),)), TableCell((Plain("b"),))),
            ['<td color="blue_bg">a</td>', "<td>b</td>"],
            id="the-first-cell-when-no-cell-holds-a-badge",
        ),
        pytest.param(
            (TableCell((Chip("x", "red"),), "danger"), TableCell((Plain("b"),))),
            ['<td color="red_bg">**x**</td>', "<td>b</td>"],
            id="a-cell-tone-wins-over-the-row-tone",
        ),
        pytest.param(
            (TableCell((Plain("a"),)), TableCell((Chip("x", "red"),)), TableCell((Chip("y", "blue"),))),
            ["<td>a</td>", '<td color="blue_bg">**x**</td>', '<td><span color="blue">**y**</span></td>'],
            id="a-badge-outside-the-filled-cell-keeps-its-colour",
        ),
    ],
)
def test_a_toned_row_fills_one_cell_not_the_whole_row(cells: tuple[TableCell, ...], lines: list[str]) -> None:
    names = "ABC"[: len(cells)]
    table = TableNode(tuple(TableCell((Plain(name),)) for name in names), (TableRow(cells, "info"),))

    assert render_notion([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n" + "".join(f"\t\t<td>**{name}**</td>\n" for name in names) + "\t</tr>\n"
        "\t<tr>\n" + "".join(f"\t\t{line}\n" for line in lines) + "\t</tr>\n"
        "</table>\n"
    )


def test_a_badge_in_a_column_filled_by_its_tone_takes_the_normal_colour() -> None:
    table = TableNode(
        (TableCell((Plain("A"),)), TableCell((Plain("B"),))),
        (TableRow((TableCell((Chip("x", "red"),)), TableCell((Chip("y", "red"),)))),),
        columns=(TableColumn(), TableColumn(tone="info")),
    )

    assert render_notion([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        '\t<colgroup>\n\t\t<col>\n\t\t<col color="blue_bg">\n\t</colgroup>\n'
        "\t<tr>\n\t\t<td>**A**</td>\n\t\t<td>**B**</td>\n\t</tr>\n"
        '\t<tr>\n\t\t<td><span color="red">**x**</span></td>\n\t\t<td>**y**</td>\n\t</tr>\n'
        "</table>\n"
    )


@pytest.mark.parametrize(
    ("row", "header_column", "line"),
    [
        pytest.param(
            TableRow((TableCell((Plain("9"),)), TableCell((Chip("x", "red"),))), "warning", emphasis="total"),
            False,
            '\t<tr>\n\t\t<td>**9**</td>\n\t\t<td color="yellow_bg">**x**</td>\n\t</tr>\n',
            id="a-toned-total-row-fills-its-badge-cell-and-bolds-it-once",
        ),
        pytest.param(
            TableRow(
                (TableCell((Plain("g "), Chip("x", "red"))), TableCell(())), "warning", emphasis="group"
            ),
            False,
            '\t<tr color="yellow_bg">\n\t\t<td>**g x**</td>\n\t\t<td></td>\n\t</tr>\n',
            id="a-group-row-holding-a-badge-stays-a-full-band",
        ),
        pytest.param(
            TableRow((TableCell((Plain("a"),)), TableCell((Plain("b"),))), "info"),
            True,
            '\t<tr>\n\t\t<td color="blue_bg">**a**</td>\n\t\t<td>b</td>\n\t</tr>\n',
            id="the-bold-header-column-cell-takes-the-fill",
        ),
    ],
)
def test_a_toned_row_fill_meets_bold_rows_and_columns(row: TableRow, header_column: bool, line: str) -> None:
    table = TableNode(
        (TableCell((Plain("A"),)), TableCell((Plain("B"),))), (row,), header_column=header_column
    )
    opening = '<table fit-page-width="true" header-row="true"' + (
        ' header-column="true">' if header_column else ">"
    )

    assert render_notion([table]) == (
        f"{opening}\n\t<tr>\n\t\t<td>**A**</td>\n\t\t<td>**B**</td>\n\t</tr>\n{line}</table>\n"
    )


def test_a_badge_in_a_bold_cell_is_not_bolded_a_second_time() -> None:
    table = TableNode(
        (TableCell((Plain("Name"),)),),
        (TableRow((TableCell((Plain("x "), Chip("New", "violet"))),)),),
        header_column=True,
    )

    assert render_notion([table]) == (
        '<table fit-page-width="true" header-row="true" header-column="true">\n'
        "\t<tr>\n\t\t<td>**Name**</td>\n\t</tr>\n"
        '\t<tr>\n\t\t<td>**x <span color="purple">New</span>**</td>\n\t</tr>\n'
        "</table>\n"
    )


def test_a_card_fills_its_callout_with_its_tone_and_keeps_a_badge_of_another_colour() -> None:
    badges = {"API": {"label": "api", "tone": "blue", "legend": False}}
    cards = {"type": "cards", "items": [{"label": "Err", "value": "3", "tone": "danger", "badges": ["API"]}]}

    assert notion_of([cards], badges=badges) == (
        '<callout icon="🛑" color="red_bg">\n\t**Err**\n\t3 <span color="blue">**api**</span>\n</callout>\n'
    )


def test_a_badge_in_a_header_cell_is_bolded_once_with_the_header() -> None:
    table = TableNode((TableCell((Chip("New", "violet"),)),), ())

    assert render_notion([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        '\t<tr>\n\t\t<td>**<span color="purple">New</span>**</td>\n\t</tr>\n'
        "</table>\n"
    )


def test_a_group_row_with_its_own_tone_keeps_that_background() -> None:
    table = TableNode(
        (TableCell((Plain("Name"),)),),
        (TableRow((TableCell((Plain("group"),)),), "warning", emphasis="group"),),
    )

    assert render_notion([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**Name**</td>\n\t</tr>\n"
        '\t<tr color="yellow_bg">\n\t\t<td>**group**</td>\n\t</tr>\n'
        "</table>\n"
    )


def test_a_swimlane_header_and_lane_cells_are_bold_as_a_whole() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["Ops"],
        "columns": [{"name": "Plan", "sub": "wk 1"}],
        "groups": [{"name": "Q1", "color": "blue", "columns": ["Plan"]}],
        "steps": [{"lane": "Ops", "col": "Plan", "n": "1", "label": "Draft", "value": 2}],
    }

    assert notion_of([swimlane]) == (
        '<table fit-page-width="true" header-row="true" header-column="true">\n'
        "\t<tr>\n\t\t<td>**Lane**</td>\n\t\t<td>**Plan<br>*wk 1*<br>Q1 (2)**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Ops (2)**</td>\n\t\t<td>**1** Draft (2)</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Total**</td>\n\t\t<td>**2**</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_grouped_table_bolds_its_group_rows_and_its_totals_row_as_a_whole() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "Issue"}, {"key": "n", "label": "Units", "kind": "number"}],
        "totals": {"column": "n"},
        "groups": [{"name": "Ours", "rows": [{"a": "x", "n": 2}]}],
    }

    assert notion_of([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        '\t<colgroup>\n\t\t<col width="637">\n\t\t<col width="71">\n\t</colgroup>\n'
        "\t<tr>\n\t\t<td>**Issue**</td>\n\t\t<td>**Units**</td>\n\t</tr>\n"
        '\t<tr color="gray_bg">\n\t\t<td>**Ours (2)**</td>\n\t\t<td></td>\n\t</tr>\n'
        "\t<tr>\n\t\t<td>x</td>\n\t\t<td>2</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>**Total**</td>\n\t\t<td>**2**</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_grid_becomes_columns_and_a_grid_inside_a_cell_stacks() -> None:
    inner = {
        "type": "grid",
        "cells": [
            {"span": 3, "blocks": [{"type": "text", "body": "b"}]},
            {"span": 3, "blocks": [{"type": "text", "body": "c"}]},
        ],
    }
    grid = {
        "type": "grid",
        "cells": [{"span": 2, "blocks": [{"type": "text", "body": "a"}]}, {"span": 4, "blocks": [inner]}],
    }

    assert notion_of([grid]) == (
        "<columns>\n"
        '\t<column ratio="33">\n\t\ta\n\t</column>\n'
        '\t<column ratio="67">\n\t\tb\n\t\tc\n\t</column>\n'
        "</columns>\n"
    )


def test_nested_list_children_are_indented_with_tabs() -> None:
    block = {
        "type": "list",
        "items": [{"text": "parent", "items": ["child", {"text": "mid", "items": ["leaf"]}]}],
    }

    assert notion_of([block]) == "- parent\n\t- child\n\t- mid\n\t\t- leaf\n"


@pytest.mark.parametrize(
    ("options", "notion"),
    [
        pytest.param({"start": 1}, "1. c\n2. d\n\t1. e\n", id="a-start-of-one-is-native"),
        pytest.param({"numbering": "decimal"}, "1. c\n2. d\n\t1. e\n", id="decimal-is-native"),
        pytest.param(
            {"numbering": "letters"}, "- a. c\n- b. d\n\t- a. e\n", id="letters-are-bullets-led-by-the-letter"
        ),
        pytest.param(
            {"start": 4, "numbering": "roman"},
            "- iv. c\n- v. d\n\t- i. e\n",
            id="roman-is-bullets-led-by-the-numeral-from-the-start",
        ),
    ],
)
def test_a_numbered_list_keeps_its_start_and_its_numbering(options: dict[str, object], notion: str) -> None:
    block = {"type": "list", "style": "number", "items": ["c", {"text": "d", "items": ["e"]}], **options}

    assert notion_of([block]) == notion


def test_the_notion_writer_refuses_a_numbered_list_starting_past_1_as_an_invariant() -> None:
    with pytest.raises(ExportInvariantError) as raised:
        render_notion([ListNode("number", (ListEntry((Plain("three"),)),), start=3)])

    assert str(raised.value) == (
        "Notion numbers every list from 1, not from 3; the export check should have refused it"
    )


def test_a_callout_and_a_note_icon_replace_the_tone_icon_of_the_native_callout() -> None:
    blocks = [
        {"type": "callout", "tone": "danger", "icon": "🔥", "body": "hot"},
        {"type": "note", "icon": "📌", "title": "Aside", "body": "x"},
    ]

    assert notion_of(blocks) == (
        '<callout icon="🔥" color="red_bg">\n\thot\n</callout>\n'
        '<callout icon="📌" color="gray_bg">\n\t**Aside**\n\tx\n</callout>\n'
    )


def test_a_decision_list_is_a_bullet_list_led_by_decided_and_open_glyphs() -> None:
    block = {"type": "list", "style": "decision", "items": ["open", {"text": "done", "decided": True}]}

    assert notion_of([block]) == "- ❓ open\n- ☑️ done\n"


def test_a_nested_decision_list_marks_every_level_and_reads_apart_from_a_check_list() -> None:
    blocks = [
        {
            "type": "list",
            "style": "decision",
            "items": [
                {"text": "region", "decided": True, "items": ["failover", {"text": "zone", "decided": True}]}
            ],
        },
        {"type": "list", "style": "check", "items": [{"text": "shipped", "checked": True}, "tested"]},
        {"type": "status_list", "items": [{"state": "done", "text": "rolled out"}]},
    ]

    assert notion_of(blocks) == (
        "- ☑️ region\n\t- ❓ failover\n\t- ☑️ zone\n- [x] shipped\n- [ ] tested\n"
        '- <span color="green">✓</span> rolled out\n'
    )


def test_a_collapsed_section_becomes_a_toggle_heading_and_an_open_one_a_plain_heading() -> None:
    blocks = [
        {"type": "section", "title": "Appendix", "blocks": [{"type": "text", "body": "raw"}]},
        {
            "type": "section",
            "title": "Status",
            "collapsed": False,
            "blocks": [{"type": "text", "body": "now"}],
        },
    ]

    assert notion_of(blocks) == '## Appendix {toggle="true"}\n\traw\n## Status\nnow\n'


def test_a_panel_inside_a_section_becomes_a_callout_inside_the_toggle_heading() -> None:
    panel = {"type": "panel", "title": "Card", "blocks": [{"type": "text", "body": "inside"}]}
    section = {"type": "section", "title": "Appendix", "blocks": [panel]}

    assert notion_of([section]) == (
        '## Appendix {toggle="true"}\n'
        '\t<callout icon="📝" color="gray_bg">\n'
        "\t\t**Card**\n"
        "\t\tinside\n"
        "\t</callout>\n"
    )


def test_chunks_split_only_at_a_top_level_heading_and_stay_under_the_limit() -> None:
    assert _chunked(lowered(heading_sections(4, "x = 1\n" * 20)), 400) == NotionChunks(
        (
            _section_text("Part 0", "x = 1", 20) + _section_text("Part 1", "x = 1", 20),
            _section_text("Part 2", "x = 1", 20) + _section_text("Part 3", "x = 1", 20),
        ),
        (),
    )


def test_a_collapsed_section_starts_a_chunk_and_a_level_three_heading_does_not() -> None:
    blocks = [
        {"type": "heading", "text": "Open"},
        {"type": "heading", "text": "Inner", "level": 3},
        {"type": "section", "title": "Shut", "blocks": [{"type": "text", "body": "x"}]},
    ]

    assert _chunked(lowered(blocks), 30) == NotionChunks(
        ("## Open\n### Inner\n", '## Shut {toggle="true"}\n\tx\n'), ()
    )


def test_a_section_exactly_at_the_limit_fits_one_chunk() -> None:
    assert _chunked(lowered([{"type": "heading", "text": "A"}]), len("## A\n")) == NotionChunks(
        ("## A\n",), ()
    )


def test_a_section_longer_than_the_chunk_stays_whole_and_is_reported_by_its_heading() -> None:
    assert _chunked(lowered(heading_sections(2, "y = 2\n" * 40)), 100) == NotionChunks(
        (_section_text("Part 0", "y = 2", 40), _section_text("Part 1", "y = 2", 40)),
        ("## Part 0", "## Part 1"),
    )


def test_an_oversized_opening_before_the_first_heading_is_named_as_the_opening_section() -> None:
    nodes = (Paragraph((Plain("x" * 50),)), Heading(2, (Plain("A"),)))

    assert _chunked(nodes, 20) == NotionChunks(
        ("x" * 50 + "\n", "## A\n"), ("the opening section, before the first level 1 or 2 heading",)
    )


def test_an_oversized_section_is_named_by_its_heading_text_not_its_markup() -> None:
    nodes = (Toggle((Plain("Q3 [draft]"),), 2, (Paragraph((Plain("y" * 50),)),)),)

    assert _chunked(nodes, 20).oversized_sections == ("## Q3 [draft]",)


def test_two_sections_that_exactly_fill_the_limit_share_one_chunk() -> None:
    nodes = (Heading(2, (Plain("A"),)), Heading(2, (Plain("B"),)))

    assert _chunked(nodes, len("## A\n## B\n")) == NotionChunks(("## A\n## B\n",), ())


def _characters_and_blocks(most_blocks: int) -> Budget:
    return Budget(
        (Limit(characters, CHUNK_THAT_HOLDS_THE_WHOLE_PAGE), Limit(rendered_block_count, most_blocks))
    )


def test_a_block_limit_groups_sections_where_a_character_limit_would_not() -> None:
    assert chunk_notion(lowered(heading_sections(4, "x = 1\n")), _characters_and_blocks(4)) == NotionChunks(
        (
            _section_text("Part 0", "x = 1", 1) + _section_text("Part 1", "x = 1", 1),
            _section_text("Part 2", "x = 1", 1) + _section_text("Part 3", "x = 1", 1),
        ),
        (),
    )


def test_a_section_over_the_block_limit_alone_is_reported_though_its_characters_fit() -> None:
    assert chunk_notion(lowered(heading_sections(2, "x = 1\n")), _characters_and_blocks(1)) == NotionChunks(
        (_section_text("Part 0", "x = 1", 1), _section_text("Part 1", "x = 1", 1)),
        ("## Part 0", "## Part 1"),
    )


def test_an_empty_paragraph_writes_no_line() -> None:
    assert render_notion([Paragraph(()), Paragraph((Plain("x"),))]) == "x\n"


@pytest.mark.parametrize(
    ("tone", "color"),
    [
        pytest.param("neutral", "gray", id="neutral"),
        pytest.param("muted", "gray", id="muted"),
        pytest.param("info", "blue", id="info"),
        pytest.param("success", "green", id="success"),
        pytest.param("warning", "yellow", id="warning"),
        pytest.param("danger", "red", id="danger"),
        pytest.param("accent", "purple", id="accent"),
        pytest.param("teal", "brown", id="teal"),
        pytest.param("sky", "pink", id="sky"),
    ],
)
def test_every_tone_has_a_notion_block_color(tone: ToneName, color: str) -> None:
    assert render_notion([Paragraph((Plain("p"),), tone), Callout(tone, ())]) == (
        f'p {{color="{color}"}}\n<callout icon="{CALLOUT_ICON[tone]}" color="{color}_bg">\n</callout>\n'
    )


def test_back_to_back_lists_of_one_kind_get_an_empty_block_between_them_so_they_stay_two_lists() -> None:
    blocks = [
        {"type": "list", "style": "number", "items": ["a"]},
        {"type": "list", "style": "number", "items": ["b"]},
        {"type": "list", "style": "check", "items": ["c"]},
        {"type": "list", "items": ["d"]},
        {"type": "list", "items": ["e"]},
    ]

    assert notion_of(blocks) == "1. a\n<empty-block/>\n1. b\n- [ ] c\n- d\n<empty-block/>\n- e\n"


def _one_entry_list(kind: ListKind, text: str, children: tuple[Node, ...] = ()) -> ListNode:
    return ListNode(kind, (ListEntry((Plain(text),), children=children),))


@pytest.mark.parametrize(
    ("nodes", "notion"),
    [
        pytest.param(
            (_one_entry_list("check", "a"), _one_entry_list("bullet", "b")),
            "- [ ] a\n- b\n",
            id="check-then-bullet",
        ),
        pytest.param(
            (_one_entry_list("bullet", "a"), _one_entry_list("number", "b")),
            "- a\n1. b\n",
            id="bullet-then-number",
        ),
        pytest.param(
            (_one_entry_list("bullet", "a"), Paragraph(()), _one_entry_list("bullet", "b")),
            "- a\n<empty-block/>\n- b\n",
            id="an-empty-paragraph-between-writes-nothing",
        ),
        pytest.param(
            (_one_entry_list("bullet", "a"), Paragraph((Plain("p"),)), _one_entry_list("bullet", "b")),
            "- a\np\n- b\n",
            id="a-paragraph-between-keeps-them-apart",
        ),
        pytest.param(
            (
                _one_entry_list(
                    "bullet", "p", (_one_entry_list("number", "a"), _one_entry_list("number", "b"))
                ),
            ),
            "- p\n\t1. a\n\t<empty-block/>\n\t1. b\n",
            id="inside-a-list-entry",
        ),
        pytest.param(
            (Callout("info", (_one_entry_list("check", "a"), _one_entry_list("check", "b"))),),
            '<callout icon="💡" color="blue_bg">\n\t- [ ] a\n\t<empty-block/>\n\t- [ ] b\n</callout>\n',
            id="inside-a-callout",
        ),
    ],
)
def test_an_empty_block_separates_only_lists_of_the_same_kind_that_notion_would_merge(
    nodes: tuple[Node, ...], notion: str
) -> None:
    assert render_notion(nodes) == notion


OPENING_THAT_RENDERS_NOTHING = (Paragraph(()), Heading(2, (Plain("A"),)), Paragraph((Plain("a"),)))
SECTIONS_WITH_LISTS = (
    _one_entry_list("bullet", "intro"),
    Heading(2, (Plain("A"),)),
    _one_entry_list("bullet", "a"),
    _one_entry_list("bullet", "b"),
    Toggle((Plain("B"),), 2, (Paragraph(()),)),
    Heading(1, (Plain("C"),)),
)


@pytest.mark.parametrize(
    "nodes",
    [
        pytest.param(OPENING_THAT_RENDERS_NOTHING, id="opening-renders-nothing"),
        pytest.param((), id="empty-body"),
        pytest.param((Paragraph(()),), id="body-renders-nothing"),
        pytest.param(SECTIONS_WITH_LISTS, id="sections-with-lists"),
        pytest.param(lowered(heading_sections(4, "x = 1\n" * 20)), id="code-sections"),
    ],
)
@pytest.mark.parametrize(
    "limit", [pytest.param(limit, id=f"limit-{limit}") for limit in (1, 20, 400, 100000)]
)
def test_the_chunks_joined_are_the_whole_page(nodes: tuple[Node, ...], limit: int) -> None:
    assert "".join(_chunked(nodes, limit).chunks) == render_notion(nodes)


def test_a_chunked_export_of_a_document_with_a_deep_heading_splits_where_it_did_and_moves_every_heading(
    tmp_path: Path,
) -> None:
    deep_section = {
        "type": "section",
        "title": "Part 1",
        "collapsed": False,
        "blocks": [
            {"type": "heading", "level": 3, "text": "Zone C"},
            {"type": "heading", "level": 4, "text": "Bin 12"},
            {"type": "code", "content": "z = 3\n" * 20},
        ],
    }
    first_section = {
        "type": "section",
        "title": "Part 0",
        "collapsed": False,
        "blocks": [{"type": "code", "content": "z = 3\n" * 20}],
    }
    report = parse_report(make_report(meta={"title": "Count"}, blocks=[first_section, deep_section]))

    result = export_notion(report, tmp_path, chunk=200)

    assert {path.name: path.read_text(encoding="utf-8") for path in result.files} == {
        "page.00.md": _section_text("Part 0", "z = 3", 20).replace("## ", "# ", 1),
        "page.01.md": "# Part 1\n### Zone C\n#### Bin 12\n```plain text\n" + "z = 3\n" * 20 + "```\n",
    }


def test_a_chunked_export_writes_one_numbered_file_per_chunk(tmp_path: Path) -> None:
    report = parse_report(make_report(meta={"title": "Count"}, blocks=heading_sections(2, "z = 3\n" * 20)))

    result = export_notion(report, tmp_path, chunk=200)

    assert result == ExportResult("Count", (tmp_path / "page.00.md", tmp_path / "page.01.md"))
    assert {path.name: path.read_text(encoding="utf-8") for path in result.files} == {
        "page.00.md": _section_text("Part 0", "z = 3", 20),
        "page.01.md": _section_text("Part 1", "z = 3", 20),
    }


@pytest.mark.parametrize(
    ("first_chunk", "second_chunk", "remaining_pages"),
    [
        pytest.param(CHUNK_THAT_SPLITS_EVERY_SECTION, None, ["page.md"], id="chunked-then-whole"),
        pytest.param(
            CHUNK_THAT_SPLITS_EVERY_SECTION,
            CHUNK_THAT_HOLDS_THE_WHOLE_PAGE,
            ["page.00.md"],
            id="many-chunks-then-one",
        ),
    ],
)
def test_a_re_export_removes_only_the_pages_its_earlier_run_wrote(
    tmp_path: Path, first_chunk: int, second_chunk: int | None, remaining_pages: list[str]
) -> None:
    report = parse_report(make_report(blocks=heading_sections(3, "w = 4\n" * 20)))
    export_notion(report, tmp_path, chunk=first_chunk)
    (tmp_path / "page.07.md").write_text("mine", encoding="utf-8")
    (tmp_path / "page.09.md").mkdir()

    export_notion(report, tmp_path, chunk=second_chunk)

    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [*remaining_pages, "page.07.md", "page.09.md", EXPORT_MANIFEST]
    )
    assert json.loads((tmp_path / EXPORT_MANIFEST).read_text(encoding="utf-8")) == {
        "title": "Test Report",
        "files": remaining_pages,
    }


def test_a_markdown_export_after_a_chunked_notion_one_in_the_same_folder_leaves_one_page(
    tmp_path: Path,
) -> None:
    report = parse_report(make_report(blocks=heading_sections(3, "w = 4\n" * 20)))
    export_notion(report, tmp_path, chunk=CHUNK_THAT_SPLITS_EVERY_SECTION)

    export_markdown(report, tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == [EXPORT_MANIFEST, "page.md"]


@pytest.mark.parametrize(
    ("manifest", "reason"),
    [
        pytest.param(None, "", id="first-export"),
        pytest.param('{"title": "T", "files": ["page.03.md"]}', "", id="manifest-lists-other-pages"),
        pytest.param("not json", ", since that list could not be read", id="unreadable-manifest"),
    ],
)
@pytest.mark.parametrize(
    "export",
    [pytest.param(export_markdown, id="markdown"), pytest.param(export_notion, id="notion")],
)
def test_an_export_refuses_to_overwrite_a_page_the_manifest_does_not_list_and_writes_nothing(
    tmp_path: Path, manifest: str | None, reason: str, export: Callable[[Report, Path], ExportResult]
) -> None:
    (tmp_path / "page.md").write_text("my own notes\n", encoding="utf-8")
    if manifest is not None:
        (tmp_path / EXPORT_MANIFEST).write_text(manifest, encoding="utf-8")
    before = folder_texts(tmp_path)

    with pytest.raises(ReportError) as refused:
        export(parse_report(make_report()), tmp_path)

    assert (str(refused.value), folder_texts(tmp_path)) == (
        f"refusing to overwrite {tmp_path / 'page.md'}, which is not on the {EXPORT_MANIFEST} list of "
        f"files skaldr wrote{reason}; move it away or choose another --export-dir",
        before,
    )


def _file_texts(folder: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in folder.iterdir() if path.is_file()}


@pytest.mark.parametrize(
    "manifest",
    [
        pytest.param(None, id="unlisted"),
        pytest.param('{"title": "T", "files": ["page.md"]}', id="listed-by-an-earlier-export"),
    ],
)
def test_an_export_refuses_a_folder_where_its_page_goes_and_writes_nothing(
    tmp_path: Path, manifest: str | None
) -> None:
    (tmp_path / "page.md").mkdir()
    (tmp_path / "page.md" / "inside.txt").write_text("mine", encoding="utf-8")
    if manifest is not None:
        (tmp_path / EXPORT_MANIFEST).write_text(manifest, encoding="utf-8")
    before = _file_texts(tmp_path)

    with pytest.raises(ReportError) as refused:
        export_markdown(parse_report(make_report()), tmp_path)

    assert (str(refused.value), _file_texts(tmp_path), folder_texts(tmp_path / "page.md")) == (
        f"refusing to overwrite {tmp_path / 'page.md'}, which is a folder, not a page file; "
        "move it away or choose another --export-dir",
        before,
        {"inside.txt": "mine"},
    )


def test_a_chunked_export_refuses_to_overwrite_numbered_pages_its_earlier_run_did_not_write(
    tmp_path: Path,
) -> None:
    shorter = parse_report(make_report(blocks=heading_sections(2, "w = 4\n" * 20)))
    export_notion(shorter, tmp_path, chunk=CHUNK_THAT_SPLITS_EVERY_SECTION)
    (tmp_path / "page.06.md").write_text("mine", encoding="utf-8")
    (tmp_path / "page.07.md").write_text("also mine", encoding="utf-8")
    before = folder_texts(tmp_path)
    longer = parse_report(make_report(blocks=heading_sections(8, "w = 4\n" * 20)))

    with pytest.raises(ReportError) as refused:
        export_notion(longer, tmp_path, chunk=CHUNK_THAT_SPLITS_EVERY_SECTION)

    assert (str(refused.value), folder_texts(tmp_path)) == (
        f"refusing to overwrite {tmp_path / 'page.06.md'}, {tmp_path / 'page.07.md'}, which are not on the "
        f"{EXPORT_MANIFEST} list of files skaldr wrote; move them away or choose another --export-dir",
        before,
    )


@pytest.mark.parametrize(
    "target_text",
    [pytest.param(None, id="dangling"), pytest.param("theirs", id="live")],
)
def test_an_export_refuses_a_symlink_where_its_page_goes_and_leaves_its_target_alone(
    tmp_path: Path, target_text: str | None
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    target = tmp_path / "target.md"
    if target_text is not None:
        target.write_text(target_text, encoding="utf-8")
    (out_dir / "page.md").symlink_to(target)

    with pytest.raises(ReportError) as refused:
        export_markdown(parse_report(make_report()), out_dir)

    assert (
        str(refused.value),
        (out_dir / "page.md").is_symlink(),
        sorted(path.name for path in out_dir.iterdir()),
        target.read_text(encoding="utf-8") if target.exists() else None,
    ) == (
        f"refusing to overwrite {out_dir / 'page.md'}, which is not on the {EXPORT_MANIFEST} list of "
        "files skaldr wrote; move it away or choose another --export-dir",
        True,
        ["page.md"],
        target_text,
    )


@pytest.mark.parametrize(
    "manifest",
    [
        pytest.param("not json", id="not-json"),
        pytest.param("[" * NESTING_TOO_DEEP_TO_PARSE, id="nested-too-deep-to-parse"),
        pytest.param('["page.03.md"]', id="not-an-object"),
        pytest.param('{"files": ["page.03.md"]}', id="no-title"),
        pytest.param('{"title": "T", "files": ["page.03.md"], "pages": 1}', id="unknown-key"),
        pytest.param('{"title": "T", "files": "page.03.md"}', id="files-not-a-list"),
        pytest.param('{"title": "T", "files": [3, null]}', id="entries-not-names"),
        pytest.param('{"title": "T", "files": ["page.03.md", 3]}', id="names-mixed-with-non-names"),
        pytest.param('{"title": "T", "files": ["README.md", "notes.txt"]}', id="names-skaldr-never-writes"),
        pytest.param(
            '{"title": "T", "files": ["../page.03.md", "sub/page.03.md"]}', id="paths-outside-the-folder"
        ),
    ],
)
def test_a_manifest_skaldr_did_not_write_deletes_nothing_and_is_reported(
    tmp_path: Path, manifest: str
) -> None:
    out_dir = tmp_path / "out"
    (out_dir / "sub").mkdir(parents=True)
    kept = [out_dir / "page.03.md", out_dir / "README.md", out_dir / "notes.txt", tmp_path / "page.03.md"]
    kept.append(out_dir / "sub" / "page.03.md")
    for path in kept:
        path.write_text("mine", encoding="utf-8")
    (out_dir / EXPORT_MANIFEST).write_text(manifest, encoding="utf-8")

    result = export_notion(parse_report(make_report()), out_dir)

    assert ([path.read_text(encoding="utf-8") for path in kept], result) == (
        ["mine"] * len(kept),
        ExportResult("Test Report", (out_dir / "page.md",), unreadable_manifest=True),
    )


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("page.03.md.bak", id="extra-suffix"),
        pytest.param("xpage.md", id="extra-prefix"),
        pytest.param("page.1.md", id="one-digit"),
        pytest.param("page.٠٣.md", id="non-ascii-digits"),
        pytest.param("page.03.md\n", id="trailing-newline"),
    ],
)
def test_a_manifest_naming_a_file_skaldr_never_writes_leaves_that_file_alone(
    tmp_path: Path, name: str
) -> None:
    (tmp_path / name).write_text("mine", encoding="utf-8")
    (tmp_path / EXPORT_MANIFEST).write_text(json.dumps({"title": "T", "files": [name]}), encoding="utf-8")

    result = export_notion(parse_report(make_report()), tmp_path)

    assert ((tmp_path / name).read_text(encoding="utf-8"), result.unreadable_manifest) == ("mine", True)


def _leave_absent(_path: Path) -> None:
    return None


@pytest.mark.parametrize(
    ("make_it_not_a_file", "expected_names"),
    [
        pytest.param(_leave_absent, [EXPORT_MANIFEST, "page.md"], id="deleted-by-hand"),
        pytest.param(Path.mkdir, [EXPORT_MANIFEST, "page.03.md", "page.md"], id="replaced-by-a-folder"),
    ],
)
def test_a_listed_page_that_is_no_longer_a_file_is_skipped_and_kept(
    tmp_path: Path, make_it_not_a_file: Callable[[Path], object], expected_names: list[str]
) -> None:
    make_it_not_a_file(tmp_path / "page.03.md")
    (tmp_path / EXPORT_MANIFEST).write_text('{"title": "T", "files": ["page.03.md"]}', encoding="utf-8")

    result = export_notion(parse_report(make_report()), tmp_path)

    assert (sorted(path.name for path in tmp_path.iterdir()), result) == (
        sorted(expected_names),
        ExportResult("Test Report", (tmp_path / "page.md",)),
    )


def test_a_page_name_that_is_a_symlink_gets_the_page_in_its_target_and_stays_a_link(tmp_path: Path) -> None:
    page_target = tmp_path / "wiki" / "page.md"
    manifest_target = tmp_path / "wiki" / "manifest.json"
    page_target.parent.mkdir()
    page_target.write_text("earlier page", encoding="utf-8")
    manifest_target.write_text('{"title": "T", "files": ["page.md"]}', encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "page.md").symlink_to(page_target)
    (out_dir / EXPORT_MANIFEST).symlink_to(manifest_target)

    export_notion(parse_report(make_report()), out_dir)

    assert (
        page_target.read_text(encoding="utf-8"),
        (out_dir / "page.md").is_symlink(),
        json.loads(manifest_target.read_text(encoding="utf-8")),
        (out_dir / EXPORT_MANIFEST).is_symlink(),
    ) == ("Hello.\n", True, {"title": "Test Report", "files": ["page.md"]}, True)


def test_a_replaced_page_keeps_the_permissions_it_had(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text("old", encoding="utf-8")
    page.chmod(0o600)
    (tmp_path / EXPORT_MANIFEST).write_text('{"title": "T", "files": ["page.md"]}', encoding="utf-8")

    export_notion(parse_report(make_report()), tmp_path)

    assert (page.read_text(encoding="utf-8"), page.stat().st_mode & 0o777) == ("Hello.\n", 0o600)


def test_a_run_that_fails_partway_still_lets_the_next_run_remove_what_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = parse_report(make_report(blocks=heading_sections(4, "w = 4\n" * 20)))
    write_bytes = Path.write_bytes

    def fail_on_the_third_page(path: Path, data: bytes) -> int:
        if path.name == "page.02.md":
            raise OSError("disk full")
        return write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_on_the_third_page)
    with pytest.raises(OSError, match="disk full"):
        export_notion(report, tmp_path, chunk=CHUNK_THAT_SPLITS_EVERY_SECTION)
    monkeypatch.undo()

    export_notion(report, tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == [EXPORT_MANIFEST, "page.md"]


def test_a_run_that_fails_partway_lists_only_the_pages_it_wrote_beside_the_earlier_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = parse_report(make_report(blocks=heading_sections(4, "w = 4\n" * 20)))
    export_notion(report, tmp_path)
    write_bytes = Path.write_bytes

    def fail_on_the_second_page(path: Path, data: bytes) -> int:
        if path.name == "page.01.md":
            raise OSError("disk full")
        return write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_on_the_second_page)
    with pytest.raises(OSError, match="disk full"):
        export_notion(report, tmp_path, chunk=CHUNK_THAT_SPLITS_EVERY_SECTION)
    monkeypatch.undo()

    assert (
        json.loads((tmp_path / EXPORT_MANIFEST).read_text(encoding="utf-8")),
        sorted(path.name for path in tmp_path.iterdir()),
    ) == (
        {"title": "Test Report", "files": ["page.00.md", "page.md"]},
        [EXPORT_MANIFEST, "page.00.md", "page.md"],
    )


def test_a_hundred_chunks_or_more_are_numbered_so_they_sort_in_order(tmp_path: Path) -> None:
    report = parse_report(make_report(blocks=heading_sections(101, "v")))

    result = export_notion(report, tmp_path, chunk=1)

    assert [path.name for path in result.files] == [f"page.{index:03d}.md" for index in range(101)]


@pytest.mark.parametrize(
    ("block", "page"),
    [
        pytest.param(
            {"type": "callout", "tone": "warning", "title": "List", "body": "- first with `code`\n- second"},
            '<callout icon="⚠️" color="yellow_bg">\n'
            "\t**List**\n\t- first with `code`\n\t- second\n</callout>\n",
            id="callout-whose-body-is-a-list",
        ),
        pytest.param(
            {"type": "def_list", "items": [{"term": "Why", "body": "- one\n- two\n\nAfter."}]},
            "**Why**\n\t- one\n\t- two\n\tAfter.\n",
            id="definition-that-opens-with-a-list",
        ),
        pytest.param(
            {"type": "quote", "body": "Said:\n\n2. b\n3. c"},
            "> Said:<br>2\\. b<br>3\\. c\n",
            id="quote-lines-carry-their-markers",
        ),
        pytest.param(
            {"type": "text", "body": "Intro\n- a\n- b"},
            "Intro\n- a\n- b\n",
            id="text-body",
        ),
        pytest.param(
            {"type": "def_list", "items": [{"term": "Why", "body": "Intro.\n- a\n- b"}]},
            "**Why**\n\tIntro.\n\t- a\n\t- b\n",
            id="definition-with-a-paragraph-before-its-list",
        ),
        pytest.param(
            {"type": "callout", "tone": "info", "body": "1. a\n2. b"},
            '<callout icon="💡" color="blue_bg">\n\t1. a\n\t2. b\n</callout>\n',
            id="a-numbered-list-from-one-is-native",
        ),
        pytest.param(
            {"type": "text", "body": "- a\n- b\n\nOutro\n\n- c\n- d\n* e\n* f"},
            "- a\n- b\nOutro\n- c\n- d\n<empty-block/>\n- e\n- f\n",
            id="a-paragraph-between-lists-and-a-marker-change",
        ),
        pytest.param(
            {"type": "callout", "tone": "info", "body": "- a\n- b\n  - x\n  - y"},
            '<callout icon="💡" color="blue_bg">\n\t- a\n\t- b\n\t\t- x\n\t\t- y\n</callout>\n',
            id="a-nested-list",
        ),
    ],
)
def test_list_lines_in_prose_become_notion_lists(block: dict[str, Any], page: str) -> None:
    assert notion_of([block]) == page


def test_list_lines_in_a_table_cell_are_bulleted_lines_since_a_notion_cell_holds_only_text() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "A", "kind": "rich"}],
        "rows": [{"a": "Steps:\n- one\n- two"}],
    }

    assert notion_of([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**A**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>Steps:<br>• one<br>• two</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_nested_list_in_a_quote_is_the_quote_children_nested_as_written() -> None:
    quote = {"type": "quote", "body": "- a\n- b\n  - x\n  - y"}

    assert notion_of([quote]) == ">\n\t- a\n\t- b\n\t\t- x\n\t\t- y\n"


def _two_column_table(columns: tuple[TableColumn, ...] = ()) -> TableNode:
    return TableNode(
        (TableCell((Plain("Level"),)), TableCell((Plain("In one line"),))),
        (TableRow((TableCell((Plain("New"),)), TableCell((Plain("x" * 80),)))),),
        columns=columns,
    )


def _widths_page(widths: list[int]) -> str:
    cols = "".join(f'\t\t<col width="{width}">\n' for width in widths)
    return (
        '<table fit-page-width="true" header-row="true">\n'
        f"\t<colgroup>\n{cols}\t</colgroup>\n"
        "\t<tr>\n\t\t<td>**Level**</td>\n\t\t<td>**In one line**</td>\n\t</tr>\n"
        f"\t<tr>\n\t\t<td>New</td>\n\t\t<td>{'x' * 80}</td>\n\t</tr>\n"
        "</table>\n"
    )


@pytest.mark.parametrize(
    ("columns", "widths"),
    [
        pytest.param((), [141, 1059], id="unsized-columns-share-by-their-longest-text-clamped-to-8-and-60"),
        pytest.param(
            (TableColumn(share=0.25), TableColumn(share=0.75)),
            [300, 900],
            id="author-widths-keep-their-ratio",
        ),
    ],
)
def test_a_full_width_page_sizes_every_table_to_1200_pixels(
    columns: tuple[TableColumn, ...], widths: list[int]
) -> None:
    assert render_notion([_two_column_table(columns)], page_width="full") == _widths_page(widths)


def test_a_short_column_beside_many_long_ones_keeps_a_readable_width() -> None:
    header = (TableCell((Plain("%"),)), *(TableCell((Plain(f"Long {index}"),)) for index in range(5)))
    row = TableRow((TableCell((Plain("55"),)), *(TableCell((Plain("y" * 80),)) for _ in range(5))))

    page = render_notion([TableNode(header, (row,))], page_width="full")

    widths = [int(width) for width in re.findall(r'<col width="(\d+)">', page)]
    assert widths == [64, 228, 227, 227, 227, 227]


def test_a_table_in_a_half_width_column_is_sized_to_its_column() -> None:
    grid = Columns((GridColumn(50, (_two_column_table(),)), GridColumn(50, ())))

    page = render_notion([grid], page_width="full")

    assert '\t\t\t\t<col width="71">\n\t\t\t\t<col width="529">\n' in page


def test_a_normal_width_page_leaves_an_unsized_table_to_notion() -> None:
    assert "<colgroup>" not in render_notion([_two_column_table()], page_width="normal")


def test_a_normal_width_page_sizes_a_table_in_a_grid_column_to_the_whole_page_as_before() -> None:
    table = _two_column_table((TableColumn(share=0.3), TableColumn(share=0.7)))
    grid = Columns((GridColumn(50, (table,)), GridColumn(50, ())))

    assert '\t\t\t\t<col width="212">\n\t\t\t\t<col width="496">\n' in render_notion(
        [grid], page_width="normal"
    )


def test_unsized_columns_beside_a_sized_one_share_the_rest_by_their_longest_text() -> None:
    table = TableNode(
        (TableCell((Plain("n"),)), TableCell((Plain("Short"),)), TableCell((Plain("x" * 60),))),
        (),
        columns=(TableColumn(share=0.1), TableColumn(), TableColumn()),
    )

    page = render_notion([table], page_width="full")

    assert [int(width) for width in re.findall(r'<col width="(\d+)">', page)] == [120, 127, 953]


def test_a_long_header_widens_its_column_as_much_as_long_body_text_does() -> None:
    table = TableNode(
        (TableCell((Plain("h" * 60),)), TableCell((Plain("b"),))),
        ((TableRow((TableCell((Plain("a"),)), TableCell((Plain("b" * 60),)))),)),
    )

    page = render_notion([table], page_width="full")

    assert [int(width) for width in re.findall(r'<col width="(\d+)">', page)] == [600, 600]


@pytest.mark.parametrize(
    "container",
    [
        pytest.param(
            ListNode("bullet", (ListEntry((Plain("e"),), children=(_two_column_table(),)),)), id="list"
        ),
        pytest.param(Callout("info", (_two_column_table(),)), id="callout"),
        pytest.param(Toggle((Plain("t"),), None, (_two_column_table(),)), id="toggle"),
        pytest.param(Tabs((Tab((Plain("t"),), (_two_column_table(),)),)), id="tabs"),
        pytest.param(
            Diagram(Graph("LR", (GraphNode("s1", "A"),), (), "flow"), (_two_column_table(),)), id="diagram"
        ),
    ],
)
def test_a_table_nested_in_any_block_is_sized_to_the_full_page(container: Node) -> None:
    page = render_notion([container], page_width="full")

    assert [int(width) for width in re.findall(r'<col width="(\d+)">', page)] == [141, 1059]


def test_a_chunked_full_width_export_sizes_its_tables(tmp_path: Path) -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "notion_width": "full"},
            blocks=[
                make_table(
                    [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}], rows=[{"a": "x", "b": "y"}]
                )
            ],
        )
    )

    export_notion(report, tmp_path, chunk=10_000)

    assert '<col width="600">' in (tmp_path / "page.00.md").read_text(encoding="utf-8")


def test_a_row_wider_than_its_header_reads_no_column_tone_past_the_last_column() -> None:
    table = TableNode(
        (TableCell((Plain("A"),)),),
        (TableRow((TableCell((Chip("x", "red"),)), TableCell((Chip("y", "red"),)))),),
        columns=(TableColumn(tone="info"),),
    )

    assert '\t\t<td>**x**</td>\n\t\t<td><span color="red">**y**</span></td>\n' in render_notion([table])


def test_the_document_meta_chooses_the_notion_page_width(tmp_path: Path) -> None:
    report = parse_report(
        make_report(
            meta={"title": "T", "notion_width": "full"},
            blocks=[
                make_table(
                    [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}], rows=[{"a": "x", "b": "y"}]
                )
            ],
        )
    )

    export_notion(report, tmp_path)

    assert '<col width="600">\n\t\t<col width="600">' in (tmp_path / "page.md").read_text(encoding="utf-8")


def _long_table(rows: int) -> TableNode:
    return TableNode(
        (TableCell((Plain("Name"),)), TableCell((Plain("Note"),))),
        tuple(
            TableRow((TableCell((Plain(f"row {index}"),)), TableCell((Plain("n" * 30),))))
            for index in range(rows)
        ),
    )


def test_a_table_longer_than_the_chunk_stays_one_table_with_its_heading_and_is_reported() -> None:
    nodes = [Heading(2, (Plain("Big"),)), _long_table(12)]

    assert _chunked(nodes, 400) == NotionChunks((render_notion(nodes),), ("## Big",))


def test_a_long_table_mid_section_gets_a_chunk_of_its_own_and_stays_one_table() -> None:
    nodes = [
        Heading(2, (Plain("Big"),)),
        Paragraph((Plain("before"),)),
        _long_table(12),
        Paragraph((Plain("after"),)),
    ]

    assert _chunked(nodes, 400) == NotionChunks(
        (render_notion(nodes[:2]), render_notion(nodes[2:3]), render_notion(nodes[3:])), ("## Big",)
    )


def test_a_long_full_width_table_stays_whole_with_the_widths_of_the_unchunked_page() -> None:
    table = TableNode(
        (TableCell((Plain("Name"),)), TableCell((Plain("Note"),))),
        tuple(
            TableRow(
                (TableCell((Plain(f"row {index}"),)), TableCell((Plain("n" * (5 if index < 10 else 80)),)))
            )
            for index in range(12)
        ),
    )

    assert _chunked([table], 400, page_width="full") == NotionChunks(
        (render_notion([table], "full"),), ("the opening section, before the first level 1 or 2 heading",)
    )


def test_a_table_with_no_rows_longer_than_the_chunk_stays_and_is_reported() -> None:
    table = TableNode((TableCell((Plain("H" * 100),)),), ())

    split = _chunked([Heading(2, (Plain("S"),)), table], 50)

    assert split == NotionChunks((render_notion([Heading(2, (Plain("S"),)), table]),), ("## S",))


def test_a_collapsed_toggle_heading_is_a_block_and_does_not_move_with_the_next_one() -> None:
    toggle = Toggle((Plain("T"),), 3, (Paragraph((Plain("t" * 20),)),))
    nodes = [Heading(2, (Plain("S"),)), toggle, Paragraph((Plain("p" * 40),))]
    first = render_notion(nodes[:2])

    split = _chunked(nodes, len(first) + 10)

    assert split.chunks == (first, render_notion(nodes[2:]))


def test_a_heading_mid_section_moves_to_the_part_with_the_block_it_introduces() -> None:
    nodes = [
        Heading(2, (Plain("S"),)),
        Paragraph((Plain("a" * 30),)),
        Heading(3, (Plain("H3"),)),
        Heading(4, (Plain("H4"),)),
        Paragraph((Plain("b" * 60),)),
    ]

    split = _chunked(nodes, 80)

    assert split == NotionChunks(("## S\n" + "a" * 30 + "\n", "### H3\n#### H4\n" + "b" * 60 + "\n"), ())


def test_chunk_boundaries_stay_at_the_same_headings_when_a_deep_heading_moves_the_document_up() -> None:
    nodes = [
        Heading(2, (Plain("A"),)),
        Paragraph((Plain("a" * 30),)),
        Heading(2, (Plain("B"),)),
        Heading(5, (Plain("Deep"),)),
        Paragraph((Plain("b" * 30),)),
        Heading(2, (Plain("C"),)),
        Paragraph((Plain("c" * 30),)),
    ]

    split = _chunked(nodes, 60)

    assert split == NotionChunks(
        ("# A\n" + "a" * 30 + "\n", "# B\n#### Deep\n" + "b" * 30 + "\n", "# C\n" + "c" * 30 + "\n"), ()
    )


def test_a_heading_mid_section_moves_with_its_block_when_a_deep_heading_moves_the_document_up() -> None:
    nodes = [
        Heading(2, (Plain("S"),)),
        Paragraph((Plain("a" * 30),)),
        Heading(3, (Plain("H3"),)),
        Heading(5, (Plain("H5"),)),
        Paragraph((Plain("b" * 60),)),
    ]

    split = _chunked(nodes, 80)

    assert split == NotionChunks(("# S\n" + "a" * 30 + "\n", "## H3\n#### H5\n" + "b" * 60 + "\n"), ())


def test_an_oversized_section_is_named_by_the_heading_marks_the_page_writes() -> None:
    nodes = [
        Heading(2, (Plain("Big"),)),
        Paragraph((Plain("y" * 50),)),
        Heading(5, (Plain("Deep"),)),
    ]

    assert _chunked(nodes, 20).oversized_sections == ("# Big",)


def test_a_carried_heading_counts_toward_the_part_it_starts() -> None:
    nodes = [
        Heading(2, (Plain("S"),)),
        Paragraph((Plain("a" * 40),)),
        Heading(3, (Plain("H3"),)),
        Paragraph((Plain("b" * 40),)),
        Paragraph((Plain("c" * 35),)),
    ]

    split = _chunked(nodes, 80)

    assert split == NotionChunks(
        ("## S\n" + "a" * 40 + "\n", "### H3\n" + "b" * 40 + "\n", "c" * 35 + "\n"), ()
    )


def test_a_chunk_that_opens_with_a_second_list_keeps_the_separator_so_the_chunks_join_into_the_page() -> None:
    nodes = [
        ListNode("bullet", (ListEntry((Plain("a" * 10),)),)),
        ListNode("bullet", (ListEntry((Plain("b" * 10),)),)),
    ]

    split = _chunked(nodes, 30)

    assert (split, "".join(split.chunks)) == (
        NotionChunks(("- " + "a" * 10 + "\n", "<empty-block/>\n- " + "b" * 10 + "\n"), ()),
        render_notion(nodes),
    )


def test_blocks_that_fill_the_chunk_exactly_stay_together() -> None:
    nodes = [Heading(2, (Plain("S"),)), Paragraph((Plain("a" * 10),)), Paragraph((Plain("b" * 10),))]
    page = render_notion(nodes)

    assert _chunked([*nodes, Paragraph((Plain("c" * 10),))], len(page)).chunks[0] == page


def test_a_long_section_splits_between_blocks_and_keeps_a_heading_with_the_block_after_it() -> None:
    paragraphs = [Paragraph((Plain(f"paragraph {index} " + "p" * 40),)) for index in range(3)]

    split = _chunked([Heading(2, (Plain("Notes"),)), *paragraphs], 100)

    assert split == NotionChunks(
        (
            "## Notes\nparagraph 0 " + "p" * 40 + "\n",
            "paragraph 1 " + "p" * 40 + "\n",
            "paragraph 2 " + "p" * 40 + "\n",
        ),
        (),
    )
