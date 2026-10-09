import json

import pytest

from skaldr.export.budget import RenderedBlock, json_bytes, json_string_bytes
from skaldr.export.notion import notion_block_count, notion_blocks
from skaldr.export.tree import Paragraph
from skaldr.richtext import Plain

TABLE = (
    '<table fit-page-width="true" header-row="true">\n'
    "\t<colgroup>\n"
    '\t\t<col width="120">\n'
    "\t</colgroup>\n"
    "\t<tr>\n"
    "\t\t<td>**Tool**</td>\n"
    "\t</tr>\n"
    "\t<tr>\n"
    "\t\t<td>Spade</td>\n"
    "\t</tr>\n"
    "</table>\n"
)
CODE = "```python\ndef sow():\n\n    - not a list\n```\n"
LONG_FENCE_CODE = "````text\n```\n- inside\n````\n"
INDENTED_CODE = "- Steps\n\t```bash\n\trake --all\n\n\t# done\n\t```\n"
MATH = "$$\nx^2\n- y\n$$\n"
CALLOUT = '<callout icon="💡" color="blue_bg">\n\tWater daily.\n\t- Morning\n</callout>\n'
TOGGLE = "<details>\n<summary>More</summary>\n\tHidden.\n</details>\n"
COLUMNS = (
    '<columns>\n\t<column ratio="1">\n\t\tLeft.\n\t</column>\n'
    '\t<column ratio="1">\n\t\tRight.\n\t</column>\n</columns>\n'
)


@pytest.mark.parametrize(
    ("text", "blocks"),
    [
        pytest.param("", 0, id="nothing"),
        pytest.param("Welcome.\n", 1, id="paragraph"),
        pytest.param("## Tools\n- Spade.\n- Rake.\n", 3, id="heading-and-list-items"),
        pytest.param("Welcome.\n\n\nBye.\n", 2, id="blank-lines-are-no-blocks"),
        pytest.param("- One\n<empty-block/>\n- Two\n", 3, id="empty-block-separator"),
        pytest.param(TABLE, 3, id="table-and-its-rows-not-cells-or-columns"),
        pytest.param(CODE, 1, id="code-block-whatever-its-lines-hold"),
        pytest.param(LONG_FENCE_CODE, 1, id="longer-fence-holds-a-shorter-one"),
        pytest.param(INDENTED_CODE, 2, id="indented-code-under-a-list-item"),
        pytest.param(MATH, 1, id="display-math"),
        pytest.param(CALLOUT, 3, id="callout-and-its-children"),
        pytest.param(TOGGLE, 2, id="toggle-without-its-summary"),
        pytest.param(COLUMNS, 5, id="column-list-columns-and-their-children"),
        pytest.param("<table_of_contents/>\n---\n", 2, id="self-closing-and-divider"),
    ],
)
def test_notion_blocks_count_each_block_a_line_opens(text: str, blocks: int) -> None:
    assert notion_block_count(text) == blocks


def test_the_notion_block_measure_counts_the_lines_of_a_rendered_block() -> None:
    block = RenderedBlock(Paragraph((Plain("x"),)), ("## Tools", "- Spade.", "```", "- code", "```"))

    assert notion_blocks(block) == notion_block_count("## Tools\n- Spade.\n```\n- code\n```\n")


def test_json_string_bytes_count_the_escaped_utf8_text_without_its_quotes() -> None:
    text = 'Sow "early".\n\tRake é 🌱\n'

    assert json_string_bytes(text) == len(json.dumps(text, ensure_ascii=False).encode("utf-8")) - 2


def test_json_bytes_add_up_across_blocks_because_the_splitter_sums_block_costs() -> None:
    first = RenderedBlock(Paragraph((Plain("a"),)), ('Say "hi"', "é"))
    second = RenderedBlock(Paragraph((Plain("b"),)), ("\tTab",))
    written_together = RenderedBlock(first.node, (*first.lines, *second.lines))

    assert json_bytes(written_together) == json_bytes(first) + json_bytes(second)
