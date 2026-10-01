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
    export_notion(load_report(EXAMPLE), tmp_path, chunk=None)

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
        "a **bold `x`** and ~~old **new**~~ see [the method](#method), "
        "[docs](https://example.com/d) [^sop] {{owner}}",
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
        "\t\t<td>`flag` \N{FULLWIDTH PLUS SIGN} default</td>",
        "\t\t<td>\\- leading dash</td>",
    ]


def test_a_plus_away_from_a_code_span_in_a_table_cell_is_left_alone() -> None:
    table = {"type": "table", "columns": [{"key": "a", "label": "A"}], "rows": [{"a": "1 + 1 and a+b"}]}

    assert "\t\t<td>1 + 1 and a+b</td>" in _notion([table]).splitlines()


@pytest.mark.parametrize(
    "block",
    [
        pytest.param(
            {"type": "badge_row", "label": "Affects:", "items": [{"label": "api", "tone": "blue"}]},
            id="badge-row",
        ),
        pytest.param(
            {
                "type": "badge_row",
                "groups": [{"label": "Affects:", "items": [{"label": "api", "tone": "blue"}]}],
            },
            id="badge-group",
        ),
    ],
)
def test_a_label_that_already_ends_in_a_colon_gets_one_colon(block: dict[str, Any]) -> None:
    assert _notion([block]).removeprefix("- ") == '**Affects**: <span color="blue_bg">api</span>\n'


def test_a_rollup_label_that_already_ends_in_a_colon_gets_one_colon() -> None:
    table = {
        "type": "table",
        "columns": [{"key": "a", "label": "A"}, {"key": "tag", "label": "", "kind": "badge"}],
        "rows": [{"a": "x", "tag": "API"}],
        "rollup": {"by": "tag", "label": "By owner:"},
    }
    badges = {"API": {"label": "api", "tone": "blue", "legend": "the API"}}

    assert '**By owner**: <span color="blue_bg">api</span> 1' in _notion([table], badges=badges).splitlines()


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
        "    classDef info fill:#e8f0fe,stroke:#1a73e8,color:#1f2328\n"
        "```\n"
    )


def test_a_request_with_several_cases_becomes_notion_tabs() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "[]"}},
        {"label": "control", "tone": "success", "response": {"body": "[1]"}},
    ]

    text = _notion([make_command_request(cases=cases)])

    lines = text.splitlines()
    tab_lines = [line for line in lines if line.startswith("\t<tab")]
    assert text.count("<tabs>") == 1
    assert [(line, lines[lines.index(line) + 1]) for line in tab_lines] == [
        ('\t<tab icon="⚠️">', "\t\tfinding"),
        ('\t<tab icon="✅">', "\t\tcontrol"),
    ]


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

    assert _notion([grid]).splitlines() == [
        "<columns>",
        '\t<column ratio="33">',
        "\t\ta",
        "\t</column>",
        '\t<column ratio="67">',
        "\t\tb",
        "\t\tc",
        "\t</column>",
        "</columns>",
    ]


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


def test_a_chunked_export_writes_one_numbered_file_per_chunk(tmp_path: Path) -> None:
    report = parse_report(make_report(blocks=_sections(2, "z = 3\n" * 20)))

    result = export_notion(report, tmp_path, chunk=200)

    assert {path.name: path.read_text(encoding="utf-8") for path in result.files} == dict(
        zip(["page.00.md", "page.01.md"], chunk_notion(lower_report(report), 200).chunks, strict=True)
    )


@pytest.mark.parametrize("target", ["notion", "markdown"])
def test_the_cli_exports_and_prints_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], target: str
) -> None:
    data_path = _write(tmp_path, make_report())

    assert main([str(data_path), "--export", target, "--export-dir", str(tmp_path / "n")]) == 0

    assert capsys.readouterr().out.splitlines() == [f"OK  {tmp_path / 'n' / 'page.md'}"]


def test_the_cli_writes_an_export_under_out_named_for_the_file_and_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_path = _write(tmp_path, make_report())
    monkeypatch.chdir(tmp_path)

    assert main([str(data_path), "--export", "markdown"]) == 0

    assert (tmp_path / "out" / "doc.markdown" / "page.md").is_file()


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
        pytest.param(
            ["--export", "markdown", "--chunk", "100"],
            "only applies with --export notion",
            id="chunk-markdown",
        ),
        pytest.param(["--export", "jira"], "invalid choice: 'jira'", id="unknown-target"),
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
