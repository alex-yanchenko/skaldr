import json
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml

from skaldr.cli import main
from skaldr.errors import ReportError
from skaldr.export import export_notion
from skaldr.export.inline import (
    AnchorLink,
    Citation,
    Code,
    InlineContext,
    Link,
    Placeholder,
    Plain,
    Styled,
    parse_rich,
)
from skaldr.export.lower import lower_report
from skaldr.export.notion import chunk_notion, notion_inline, render_notion
from skaldr.export.publish import CREATED_PAGE_ID
from skaldr.models import AnyBlock, Grid, InnerGrid, Panel, Section, Walkthrough, load_report, parse_report
from tests.conftest import REPO_ROOT
from tests.factories import make_command_request, make_report

EXAMPLE = REPO_ROOT / "data" / "example.yaml"
NOTION_GOLDEN = REPO_ROOT / "tests" / "golden" / "example.notion"
NO_CONTEXT = InlineContext(citation_numbers={}, citation_urls={}, anchor_ids=frozenset())


def _notion(blocks: list[dict[str, Any]], **meta: Any) -> str:
    return render_notion(lower_report(parse_report(make_report(blocks=blocks, **meta))))


def _block_types_in(blocks: list[Any]) -> set[str]:
    seen: set[str] = set()
    for block in blocks:
        seen.add(block.type)
        if isinstance(block, (Section, Panel)):
            seen |= _block_types_in(block.blocks)
        if isinstance(block, (Grid, InnerGrid)):
            for cell in block.cells:
                seen |= _block_types_in(cell.blocks)
        if isinstance(block, Walkthrough):
            for step in block.steps:
                seen |= _block_types_in(step.detail)
    return seen


def _every_block_type() -> set[str]:
    union = get_args(AnyBlock)
    return {get_args(model.model_fields["type"].annotation)[0] for model in union}


def test_the_export_fixture_uses_every_block_type() -> None:
    assert _block_types_in(load_report(EXAMPLE).blocks) == _every_block_type()


def test_the_example_exports_to_the_notion_golden_regenerated_by_the_export_command(tmp_path: Path) -> None:
    export_notion(load_report(EXAMPLE), tmp_path, chunk=None, targets_file=None)

    assert {path.name: path.read_text(encoding="utf-8") for path in sorted(tmp_path.iterdir())} == {
        path.name: path.read_text(encoding="utf-8") for path in sorted(NOTION_GOLDEN.iterdir())
    }


def test_rich_text_parses_into_the_runs_the_html_renders() -> None:
    context = InlineContext(
        citation_numbers={"sop": 1},
        citation_urls={"sop": "https://example.com/sop"},
        anchor_ids=frozenset({"method"}),
    )

    runs = parse_rich(
        "a **bold `x`** and ~~old **new**~~ see [the method](#method), [docs](https://example.com/d) [^sop] {{owner}}",
        context,
    )

    assert runs == (
        Plain("a "),
        Styled("bold", (Plain("bold "), Code("x"))),
        Plain(" and "),
        Styled("strike", (Plain("old "), Styled("bold", (Plain("new"),)))),
        Plain(" see "),
        AnchorLink((Plain("the method"),), "method"),
        Plain(", "),
        Link((Plain("docs"),), "https://example.com/d"),
        Plain(" "),
        Citation(1, "https://example.com/sop"),
        Plain(" "),
        Placeholder("owner"),
    )


def test_a_link_to_an_unknown_anchor_fails_the_export() -> None:
    with pytest.raises(ReportError, match=r"unknown anchor '#nowhere'"):
        parse_rich("[x](#nowhere)", NO_CONTEXT)


@pytest.mark.parametrize(
    ("text", "notion"),
    [
        pytest.param("edit README.md first", "edit `README.md` first", id="markdown-file"),
        pytest.param("run scripts/setup.sh:12", "run `scripts/setup.sh:12`", id="shell-file-with-line"),
        pytest.param("see app.py", "see `app.py`", id="python-file"),
        pytest.param("`notes.md` stays one span", "`notes.md` stays one span", id="already-code"),
        pytest.param("a readme file", "a readme file", id="no-extension"),
    ],
)
def test_a_file_name_notion_would_turn_into_a_web_link_becomes_inline_code(text: str, notion: str) -> None:
    assert notion_inline(parse_rich(text, NO_CONTEXT)) == notion


def test_notion_special_characters_are_escaped_in_text_but_not_in_code_or_link_urls() -> None:
    text = r"cost $5 [x] <y> {z} a|b 2^3 ~n c:\d and `a|b [c]` via [x|y](https://example.com/a_b?q=[1])"

    assert notion_inline(parse_rich(text, NO_CONTEXT)) == (
        r"cost \$5 \[x\] \<y\> \{z\} a\|b 2\^3 \~n c:\\d and `a|b [c]` via [x\|y](https://example.com/a_b?q=[1])"
    )


def test_a_table_cell_of_code_plus_text_stays_a_cell_not_a_bullet() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}],
        "rows": [{"a": "`flag` + default", "b": "- leading dash"}],
    }

    lines = _notion([table]).splitlines()

    assert lines[lines.index("\t<tr>", 3) + 1 : lines.index("\t<tr>", 3) + 3] == [
        "\t\t<td>`flag` \\+ default</td>",
        "\t\t<td>\\- leading dash</td>",
    ]


def test_nested_list_children_are_indented_with_tabs() -> None:
    block = {
        "type": "list",
        "items": [{"text": "parent", "items": ["child", {"text": "mid", "items": ["leaf"]}]}],
    }

    assert _notion([block]) == "- parent\n\t- child\n\t- mid\n\t\t- leaf\n"


def test_a_table_uses_the_notion_table_element_with_a_bold_header_row() -> None:
    table = {"type": "table", "columns": [{"key": "a", "label": "Name"}], "rows": [{"a": "x"}]}

    assert _notion([table]) == (
        '<table fit-page-width="true" header-row="true">\n'
        "\t<tr>\n\t\t<td>**Name**</td>\n\t</tr>\n"
        "\t<tr>\n\t\t<td>x</td>\n\t</tr>\n"
        "</table>\n"
    )


def test_a_flow_becomes_a_mermaid_diagram() -> None:
    flow = {
        "type": "flow",
        "numbered": False,
        "steps": [{"label": "Scan", "tone": "info"}, {"label": 'Say "hi"', "note": "then **stop**"}],
    }

    assert _notion([flow]) == (
        "```mermaid\n"
        "flowchart LR\n"
        '    s1["Scan"]:::info\n'
        '    s2["Say #quot;hi#quot;<br>then stop"]\n'
        "    s1 --> s2\n"
        "    classDef info fill:#e8f0fe,stroke:#1a73e8\n"
        "```\n"
    )


def test_a_request_with_several_cases_becomes_notion_tabs() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "[]"}},
        {"label": "control", "tone": "success", "response": {"body": "[1]"}},
    ]

    text = _notion([make_command_request(cases=cases)])

    assert text.count("<tabs>") == 1
    assert ['\t<tab icon="⚠️">', "\t\tfinding"] == text.splitlines()[text.splitlines().index("<tabs>") + 1 :][
        :2
    ]
    assert '\t<tab icon="✅">\n\t\tcontrol' in text


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

    assert _notion(blocks) == '## Appendix {toggle="true"}\n\traw\n## Status\nnow\n'


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

    assert _notion([grid]) == (
        '<columns>\n\t<column ratio="33">\n\t\ta\n\t</column>\n\t<column ratio="67">\n\t\tb\n\t\tc\n\t</column>\n</columns>\n'
    )


def _sections(count: int, body: str) -> list[dict[str, Any]]:
    return [
        block
        for index in range(count)
        for block in ({"type": "heading", "text": f"Part {index}"}, {"type": "code", "content": body})
    ]


def test_chunks_split_only_at_a_top_level_heading_and_stay_under_the_limit() -> None:
    nodes = lower_report(parse_report(make_report(blocks=_sections(4, "x = 1\n" * 20))))
    whole = render_notion(nodes)

    split = chunk_notion(nodes, 400)

    assert "".join(split.chunks) == whole
    assert all(len(chunk) <= 400 for chunk in split.chunks)
    assert [chunk.split("\n", 1)[0] for chunk in split.chunks] == ["## Part 0", "## Part 2"]
    assert split.oversized == ()


def test_a_section_longer_than_the_chunk_stays_whole_and_is_reported() -> None:
    nodes = lower_report(parse_report(make_report(blocks=_sections(2, "y = 2\n" * 40))))

    split = chunk_notion(nodes, 100)

    assert [chunk.split("\n", 1)[0] for chunk in split.chunks] == ["## Part 0", "## Part 1"]
    assert split.oversized == ("## Part 0", "## Part 1")


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "doc.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_an_export_without_a_page_id_creates_a_draft_and_says_where_to_record_it(tmp_path: Path) -> None:
    report = parse_report(make_report(blocks=_sections(2, "z = 3\n" * 20)))
    targets = tmp_path / "targets.json"
    targets.write_text("{}", encoding="utf-8")

    export_notion(report, tmp_path / "out", chunk=200, targets_file=targets)
    plan = json.loads((tmp_path / "out" / "publish.json").read_text(encoding="utf-8"))

    first, second = plan["calls"]
    assert (first["tool"], first["arguments"]["creation_mode"], first["content_file"]) == (
        "notion-create-pages",
        "draft",
        "page.00.md",
    )
    assert first["arguments"]["pages"][0]["content"] == (tmp_path / "out" / "page.00.md").read_text(
        encoding="utf-8"
    )
    assert second["arguments"] == {
        "page_id": CREATED_PAGE_ID,
        "command": "insert_content",
        "content": (tmp_path / "out" / "page.01.md").read_text(encoding="utf-8"),
        "position": {"type": "end"},
    }
    assert plan["record"] == {
        "value": "the id of the page call 1 creates",
        "replaces": CREATED_PAGE_ID,
        "targets_file": str(targets),
        "key": "notion.page_id",
    }


def test_an_export_with_a_page_id_replaces_that_page(tmp_path: Path) -> None:
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps({"notion": {"page_id": "page-123"}}), encoding="utf-8")

    export_notion(parse_report(make_report()), tmp_path / "out", chunk=None, targets_file=targets)
    plan = json.loads((tmp_path / "out" / "publish.json").read_text(encoding="utf-8"))

    assert [call["arguments"]["command"] for call in plan["calls"]] == ["replace_content"]
    assert plan["calls"][0]["arguments"]["page_id"] == "page-123"
    assert "record" not in plan


def test_a_new_page_goes_under_the_parent_the_targets_name(tmp_path: Path) -> None:
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps({"notion": {"parent_page_id": "parent-9"}}), encoding="utf-8")

    export_notion(parse_report(make_report()), tmp_path / "out", chunk=None, targets_file=targets)
    arguments = json.loads((tmp_path / "out" / "publish.json").read_text(encoding="utf-8"))["calls"][0][
        "arguments"
    ]

    assert (arguments["parent"], "creation_mode" in arguments) == (
        {"type": "page_id", "page_id": "parent-9"},
        False,
    )


def test_a_targets_file_with_an_unknown_notion_key_is_rejected(tmp_path: Path) -> None:
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps({"notion": {"page": "x"}}), encoding="utf-8")

    with pytest.raises(ReportError, match=r"targets file .* has an unexpected shape"):
        export_notion(parse_report(make_report()), tmp_path / "out", chunk=None, targets_file=targets)


def test_the_cli_exports_and_prints_each_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_path = _write(tmp_path, make_report())

    assert main([str(data_path), "--export", "notion", "--export-dir", str(tmp_path / "n")]) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"OK  {tmp_path / 'n' / 'page.md'}",
        f"OK  {tmp_path / 'n' / 'publish.json'}",
    ]


def test_the_cli_checks_before_it_exports_and_writes_nothing_for_an_invalid_file(tmp_path: Path) -> None:
    data_path = _write(tmp_path, make_report(blocks=[{"type": "text", "oops": 1}]))

    assert main(["--check", str(data_path), "--export", "notion", "--export-dir", str(tmp_path / "n")]) == 1

    assert not (tmp_path / "n").exists()


@pytest.mark.parametrize(
    ("argv_tail", "message"),
    [
        pytest.param(["--export", "notion", "-o", "x.html"], "--export writes its own files", id="with-out"),
        pytest.param(["--chunk", "100"], "only apply with --export", id="chunk-alone"),
        pytest.param(["--export", "notion", "--chunk", "0"], "positive character count", id="chunk-zero"),
        pytest.param(["--export", "notion", "--live"], "--export writes none", id="with-live"),
    ],
)
def test_the_cli_rejects_flags_that_do_not_fit_an_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_tail: list[str], message: str
) -> None:
    data_path = _write(tmp_path, make_report())

    with pytest.raises(SystemExit) as excinfo:
        main([str(data_path), *argv_tail])

    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_the_cli_reports_a_section_too_long_for_the_chunk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_path = _write(tmp_path, make_report(blocks=_sections(1, "w = 4\n" * 40)))

    assert (
        main([str(data_path), "--export", "notion", "--chunk", "50", "--export-dir", str(tmp_path / "n")])
        == 0
    )

    assert "warning: section '## Part 0' is longer than --chunk 50 and stays whole" in capsys.readouterr().err
