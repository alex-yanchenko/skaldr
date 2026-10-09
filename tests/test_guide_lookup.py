import re
from pathlib import Path

import pytest

from skaldr.cli import main
from skaldr.errors import UnknownGuideTopicError
from skaldr.guide_lookup import block_names, list_topics, lookup
from skaldr.models import Card, Divider, Quote, package_text

GUIDE = package_text("skill/GUIDE.md")
TABLE_HEADER = "| `type` | Purpose | Key fields |\n|---|---|---|\n"

SMALL_GUIDE = """# Small guide

intro

## Blocks

| `type` | Purpose | Key fields |
|---|---|---|
| `quote` | The first | `one` |
| `divider` | The second | `two` |

## The `quote`

Quote prose.

```yaml
## not a heading
- type: quote
```

### Quote detail

More quote.

## `meta`

Meta prose.

## Rich text

Rich prose.

## Other
"""

SMALL_GUIDE_WITHOUT_BLOCKS = SMALL_GUIDE.replace("## Blocks", "## Elsewhere")

QUOTE_FIELDS = (
    "Fields\n"
    f"  span: int | null, default null. {Quote.model_fields['span'].description}\n"
    f"  body: str, required. {Quote.model_fields['body'].description}\n"
    f"  cite: str | null, default null. {Quote.model_fields['cite'].description}"
)
DIVIDER_FIELDS = f"Fields\n  span: int | null, default null. {Divider.model_fields['span'].description}"


def _guide_section(heading: str) -> str:
    lines = GUIDE.splitlines()
    start = lines.index(heading)
    end = next(index for index in range(start + 1, len(lines)) if lines[index].startswith("## "))
    return "\n".join(lines[start:end]).rstrip()


def _blocks_table_row(name: str) -> str:
    return next(line for line in GUIDE.splitlines() if line.startswith(f"| `{name}` |"))


def _fenceless_guide_headings() -> list[str]:
    return [line for line in GUIDE.splitlines() if line.startswith("## The `")]


def test_block_names_come_from_the_block_models_without_repeats() -> None:
    names = block_names()

    assert names[:3] == ("heading", "text", "list")
    assert len(names) == len(set(names))
    assert {"request", "request_flow", "toggle", "grid", "walkthrough", "divider"} <= set(names)
    assert "part" not in names


@pytest.mark.parametrize("name", block_names())
def test_every_block_has_its_row_in_the_real_guide_table(name: str) -> None:
    assert lookup(name, GUIDE).startswith(f"{TABLE_HEADER}{_blocks_table_row(name)}\n")


@pytest.mark.parametrize("heading", _fenceless_guide_headings())
def test_every_the_block_heading_in_the_guide_names_a_real_block(heading: str) -> None:
    assert re.fullmatch(r"## The `([a-z_]+)`", heading)
    assert heading.removeprefix("## The `").removesuffix("`") in block_names()


def test_a_block_with_a_section_prints_its_row_its_section_and_its_fields() -> None:
    assert lookup("quote", SMALL_GUIDE) == (
        f"{TABLE_HEADER}"
        "| `quote` | The first | `one` |\n"
        "\n"
        "## The `quote`\n"
        "\n"
        "Quote prose.\n"
        "\n"
        "```yaml\n"
        "## not a heading\n"
        "- type: quote\n"
        "```\n"
        "\n"
        "### Quote detail\n"
        "\n"
        "More quote.\n"
        "\n"
        f"{QUOTE_FIELDS}"
    )


def test_a_block_without_a_section_prints_its_row_and_its_fields_only() -> None:
    assert lookup("divider", SMALL_GUIDE) == (
        f"{TABLE_HEADER}| `divider` | The second | `two` |\n\n{DIVIDER_FIELDS}"
    )


def test_a_guide_without_a_blocks_section_prints_the_section_and_fields_only() -> None:
    assert lookup("quote", SMALL_GUIDE_WITHOUT_BLOCKS) == (
        "## The `quote`\n"
        "\n"
        "Quote prose.\n"
        "\n"
        "```yaml\n"
        "## not a heading\n"
        "- type: quote\n"
        "```\n"
        "\n"
        "### Quote detail\n"
        "\n"
        "More quote.\n"
        "\n"
        f"{QUOTE_FIELDS}"
    )


def test_a_section_title_prints_the_whole_section_ignoring_case_and_backticks() -> None:
    assert lookup("rich TEXT", SMALL_GUIDE) == "## Rich text\n\nRich prose."
    assert lookup("meta", SMALL_GUIDE) == "## `meta`\n\nMeta prose."


def test_a_unique_title_prefix_finds_the_section() -> None:
    assert lookup("rich", SMALL_GUIDE) == "## Rich text\n\nRich prose."


def test_an_ambiguous_title_prefix_is_unknown() -> None:
    with pytest.raises(UnknownGuideTopicError):
        lookup("o", SMALL_GUIDE.replace("## Other", "## Other\n\n## Over"))


def test_a_block_name_wins_over_a_section_with_the_same_title() -> None:
    guide = SMALL_GUIDE.replace("## Other", "## Divider\n\nSection prose.")

    assert lookup("divider", guide).endswith(DIVIDER_FIELDS)


def test_the_listing_names_the_guide_sections_then_the_blocks() -> None:
    assert list_topics(SMALL_GUIDE) == (
        "Guide sections\nBlocks\nThe `quote`\n`meta`\nRich text\nOther\n\nBlocks\n" + "\n".join(block_names())
    )


def test_an_unknown_name_lists_the_blocks_and_the_sections() -> None:
    with pytest.raises(UnknownGuideTopicError) as raised:
        lookup("gamma", SMALL_GUIDE)

    assert str(raised.value) == (
        f"unknown block or section 'gamma'; the blocks are {', '.join(block_names())}; "
        "the sections are Blocks, The quote, meta, Rich text, Other"
    )


def test_a_block_with_no_options_prints_its_row_and_only_the_span_field(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--guide", "divider"])

    assert exit_code == 0
    assert capsys.readouterr().out == f"{TABLE_HEADER}{_blocks_table_row('divider')}\n\n{DIVIDER_FIELDS}\n"


def test_string_and_integer_literals_print_with_their_repr(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--guide", "request"])
    request_lines = capsys.readouterr().out.splitlines()
    main(["--guide", "heading"])
    heading_lines = capsys.readouterr().out.splitlines()

    assert (
        "  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD' | 'OPTIONS' | null, default null. "
        "The HTTP method. Required unless the call runs a `command` or records a `query`."
    ) in request_lines
    assert next(line for line in heading_lines if line.startswith("  level:")).startswith(
        "  level: 2 | 3 | 4, default 2."
    )


def test_a_union_of_blocks_prints_as_block(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--guide", "section"])

    lines = capsys.readouterr().out.splitlines()
    assert next(line for line in lines if line.startswith("  blocks:")).startswith(
        "  blocks: list[Block], required."
    )


def test_a_nested_model_prints_its_fields_one_level_deep(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--guide", "cards"])

    lines = capsys.readouterr().out.splitlines()
    items_at = next(index for index, line in enumerate(lines) if line.startswith("  items: list[Card]"))
    assert (
        lines[items_at + 1]
        == f"    label: str | null, default null. {Card.model_fields['label'].description}"
    )
    assert lines[items_at + 1 : items_at + 1 + len(Card.model_fields)][-1].startswith("    ")
    assert not any(line.startswith("      ") for line in lines)


def test_the_guide_lookup_for_request_prints_row_section_and_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--guide", "request"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert out.startswith(
        f"{TABLE_HEADER}{_blocks_table_row('request')}\n\n{_guide_section('## The `request`')}\n\nFields\n"
    )
    assert "  label: str, required. What the call is for, shown in the header." in out.splitlines()


def test_a_section_title_on_the_command_line_prints_that_section(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--guide", "Rich text"])

    assert exit_code == 0
    assert capsys.readouterr().out == f"{_guide_section('## Rich text')}\n"


def test_the_listing_flag_prints_sections_and_blocks(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--guide", "--list"])

    sections, blocks = capsys.readouterr().out.split("\n\nBlocks\n")
    assert exit_code == 0
    assert sections.startswith("Guide sections\nShape\n`meta`\n")
    assert "\nThe `request`\n" in sections
    assert blocks.splitlines() == list(block_names())


def test_a_guide_value_that_is_only_the_content_file_keeps_the_old_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = tmp_path / "report.yaml"
    content.write_text("version: 1\n", encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        main(["--guide", str(content)])

    assert raised.value.code == 2
    assert "--guide runs on its own; drop the content file" in capsys.readouterr().err


def test_a_block_name_that_is_also_a_file_in_the_cwd_still_looks_up_the_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "divider").write_text("version: 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["--guide", "divider"])

    assert exit_code == 0
    assert capsys.readouterr().out == f"{TABLE_HEADER}{_blocks_table_row('divider')}\n\n{DIVIDER_FIELDS}\n"


def test_an_unknown_name_on_the_command_line_fails_listing_blocks_and_sections(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--guide", "gamma"])

    captured = capsys.readouterr()
    sections = ", ".join(
        line.replace("`", "") for line in list_topics(GUIDE).split("\n\nBlocks\n")[0].splitlines()[1:]
    )
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == (
        f"error: unknown block or section 'gamma'; the blocks are {', '.join(block_names())}; "
        f"the sections are {sections}\n"
    )


def test_an_empty_guide_value_is_an_unknown_name(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--guide="])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("error: unknown block or section ''; the blocks are heading, ")


def test_the_listing_flag_alone_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--list"])

    assert raised.value.code == 2
    assert "--list lists the guide; use it as `--guide --list`" in capsys.readouterr().err


def test_the_listing_flag_with_a_block_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--guide", "request", "--list"])

    assert raised.value.code == 2
    assert "--list lists the guide; use it as `--guide --list`" in capsys.readouterr().err


def test_the_listing_with_another_flag_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--guide", "--list", "--strict"])

    assert raised.value.code == 2
    assert "--guide runs on its own; drop --strict" in capsys.readouterr().err
