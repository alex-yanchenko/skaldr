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


def test_a_unique_word_prefix_finds_the_section_when_no_title_starts_with_it() -> None:
    assert lookup("tex", SMALL_GUIDE) == "## Rich text\n\nRich prose."


def test_an_ambiguous_word_prefix_is_unknown() -> None:
    with pytest.raises(UnknownGuideTopicError):
        lookup("tex", SMALL_GUIDE.replace("## Other", "## Another text"))


def test_a_title_prefix_wins_over_a_word_prefix_in_another_title() -> None:
    guide = SMALL_GUIDE.replace("## Other", "## Tex starts here")

    assert lookup("tex", guide) == "## Tex starts here"


def test_a_block_name_wins_over_a_section_with_the_same_title() -> None:
    guide = SMALL_GUIDE.replace("## Other", "## Divider\n\nSection prose.")

    assert lookup("divider", guide).endswith(DIVIDER_FIELDS)


def test_the_listing_names_the_guide_sections_then_the_blocks() -> None:
    assert list_topics(SMALL_GUIDE) == (
        "Guide sections\nBlocks\nThe `quote`\n  Quote detail\n`meta`\nRich text\nOther\n\nBlocks\n"
        + "\n".join(block_names())
    )


def test_an_unknown_name_lists_the_blocks_and_the_sections() -> None:
    with pytest.raises(UnknownGuideTopicError) as raised:
        lookup("gamma", SMALL_GUIDE)

    assert str(raised.value) == (
        f"unknown block or section 'gamma'; the blocks are {', '.join(block_names())}; "
        "the sections are Blocks, The quote, Quote detail, meta, Rich text, Other"
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
        line.replace("`", "").strip() for line in list_topics(GUIDE).split("\n\nBlocks\n")[0].splitlines()[1:]
    )
    sections += ", A complete example"
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


def test_an_ambiguous_title_prefix_across_sections_is_unknown_even_beside_a_longer_title() -> None:
    guide = SMALL_GUIDE.replace("## Other", "## Over one\n\n## Over two\n\n## Reover")

    with pytest.raises(UnknownGuideTopicError):
        lookup("over", guide)


@pytest.mark.parametrize("query", ["", "   "], ids=["empty", "blank"])
def test_an_empty_or_blank_query_is_unknown(query: str) -> None:
    with pytest.raises(UnknownGuideTopicError):
        lookup(query, SMALL_GUIDE)


def test_an_exact_subsection_title_beats_a_longer_section_title_that_starts_with_it() -> None:
    guide = SMALL_GUIDE.replace("## Other", "## Overview\n\n### Over\n\nSub prose.")

    assert lookup("over", guide) == "### Over\n\nSub prose."


def test_a_subsection_title_prefix_is_unique_even_when_a_section_title_has_it_as_a_word() -> None:
    guide = SMALL_GUIDE.replace("## Other", "## All about zeta\n\n### Zeta details\n\nSub prose.")

    assert lookup("zeta", guide) == "### Zeta details\n\nSub prose."


def test_a_subsection_title_prints_that_subsection_only() -> None:
    assert lookup("Quote detail", SMALL_GUIDE) == "### Quote detail\n\nMore quote."


def test_a_subsection_title_resolves_by_unique_prefix_and_ignores_case() -> None:
    assert lookup("quote DET", SMALL_GUIDE) == "### Quote detail\n\nMore quote."


def test_a_section_title_wins_over_a_subsection_with_the_same_title() -> None:
    guide = SMALL_GUIDE.replace("### Quote detail", "### Other\n\nSub prose.").replace(
        "## Other", "## Other\n\nTop prose."
    )

    assert lookup("other", guide) == "## Other\n\nTop prose."


def test_a_title_prefix_shared_by_two_subsections_is_unknown() -> None:
    guide = SMALL_GUIDE.replace("## Other", "## Other\n\n### Zeta one\n\n### Zeta two")

    with pytest.raises(UnknownGuideTopicError):
        lookup("zeta", guide)


def test_an_ambiguous_section_prefix_does_not_fall_back_to_a_subsection() -> None:
    guide = SMALL_GUIDE.replace("## Other", "## Over one\n\n## Over two\n\n### Over detail")

    with pytest.raises(UnknownGuideTopicError):
        lookup("over", guide)


def test_a_heading_inside_a_code_fence_is_not_a_topic() -> None:
    with pytest.raises(UnknownGuideTopicError):
        lookup("not a heading", SMALL_GUIDE)


def test_a_multi_word_query_matches_from_a_word_inside_a_title() -> None:
    guide = SMALL_GUIDE.replace("## Other", "## A complete example\n\nBody.")

    assert lookup("complete example", guide) == "## A complete example\n\nBody."


def test_the_real_guide_resolves_a_publishing_subsection(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--guide", "Publishing to Notion"])

    lines = GUIDE.splitlines()
    start = lines.index("### Publishing to Notion")
    end = lines.index("### Publishing to Jira")
    assert exit_code == 0
    assert capsys.readouterr().out == "\n".join(lines[start:end]).rstrip() + "\n"


def test_the_real_listing_indents_subsections_under_their_section(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["--guide", "--list"])

    sections = capsys.readouterr().out.split("\n\nBlocks\n")[0].splitlines()
    publishing = sections.index("Publishing")
    assert sections[publishing : publishing + 4] == [
        "Publishing",
        "  Publishing to Notion",
        "  Publishing to Jira",
        "  Publishing to Slack",
    ]


@pytest.mark.parametrize(
    "query",
    ["example", "complete example", "A complete example"],
    ids=["word-prefix", "phrase-from-a-word", "whole-title"],
)
def test_the_complete_example_is_a_section_the_guide_looks_up(
    query: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--guide", query])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert out.startswith("## A complete example\n\n```yaml\n")
    assert out.endswith("```\n")


def test_the_listing_names_the_complete_example_last_among_the_sections(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["--guide", "--list"])

    sections = capsys.readouterr().out.split("\n\nBlocks\n")[0].splitlines()
    assert sections[-1] == "A complete example"


def test_the_bare_guide_still_ends_with_the_complete_example(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--guide"])

    out = capsys.readouterr().out
    assert out.startswith(GUIDE.rstrip())
    assert "\n## A complete example\n\n```yaml\n" in out
    assert out.rstrip().endswith("```")
