from pathlib import Path

import pytest

from skaldr.cli import main
from skaldr.errors import UnknownGuideTopicError
from skaldr.guide_lookup import block_names, describe_block, list_topics
from skaldr.models import Divider, package_text

GUIDE = package_text("skill/GUIDE.md")

SMALL_GUIDE = """# Small guide

intro

## Blocks

| `type` | Purpose | Key fields |
|---|---|---|
| `alpha` | The first | `one` |
| `beta` | The second | `two` |

## The `alpha`

Alpha prose.

```yaml
## not a heading
- type: alpha
```

### Alpha detail

More alpha.

## The `beta`

Beta prose.

## Other
"""


def _guide_section(heading: str) -> str:
    lines = GUIDE.splitlines()
    start = lines.index(heading)
    end = next(index for index in range(start + 1, len(lines)) if lines[index].startswith("## "))
    return "\n".join(lines[start:end]).rstrip()


def _blocks_table_row(name: str) -> str:
    return next(line for line in GUIDE.splitlines() if line.startswith(f"| `{name}` |"))


def test_block_names_come_from_the_block_models_without_repeats() -> None:
    names = block_names()

    assert names[:3] == ("heading", "text", "list")
    assert len(names) == len(set(names))
    assert {"request", "request_flow", "toggle", "grid", "walkthrough", "divider"} <= set(names)
    assert "part" not in names


def test_a_block_with_a_section_prints_its_row_its_section_and_its_fields() -> None:
    out = describe_block(
        "alpha", SMALL_GUIDE, names=("alpha", "beta"), fields_of=lambda _name: "Fields\n  one: str"
    )

    assert out == (
        "| `type` | Purpose | Key fields |\n"
        "|---|---|---|\n"
        "| `alpha` | The first | `one` |\n"
        "\n"
        "## The `alpha`\n"
        "\n"
        "Alpha prose.\n"
        "\n"
        "```yaml\n"
        "## not a heading\n"
        "- type: alpha\n"
        "```\n"
        "\n"
        "### Alpha detail\n"
        "\n"
        "More alpha.\n"
        "\n"
        "Fields\n"
        "  one: str"
    )


def test_a_block_without_a_section_prints_its_row_and_its_fields_only() -> None:
    sectionless = SMALL_GUIDE.replace("## The `beta`\n\nBeta prose.\n\n", "")

    out = describe_block(
        "beta", sectionless, names=("alpha", "beta"), fields_of=lambda _name: "Fields\n  two: str"
    )

    assert out == (
        "| `type` | Purpose | Key fields |\n"
        "|---|---|---|\n"
        "| `beta` | The second | `two` |\n"
        "\n"
        "Fields\n"
        "  two: str"
    )


def test_a_block_with_no_table_row_and_no_section_prints_its_fields_only() -> None:
    out = describe_block(
        "gamma", SMALL_GUIDE, names=("alpha", "gamma"), fields_of=lambda _name: "Fields\n  g: str"
    )

    assert out == "Fields\n  g: str"


def test_the_listing_names_the_guide_sections_then_the_blocks() -> None:
    assert list_topics(SMALL_GUIDE, names=("alpha", "beta")) == (
        "Guide sections\nBlocks\nThe `alpha`\nThe `beta`\nOther\n\nBlocks\nalpha\nbeta"
    )


def test_an_unknown_block_names_the_valid_ones() -> None:
    with pytest.raises(UnknownGuideTopicError) as raised:
        describe_block("gamma", SMALL_GUIDE, names=("alpha", "beta"), fields_of=lambda _name: "")

    assert str(raised.value) == "unknown block 'gamma'; the blocks are alpha, beta"


def test_the_guide_lookup_for_a_block_with_no_options_prints_whole(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--guide", "divider"])

    span = Divider.model_fields["span"].description
    assert exit_code == 0
    assert capsys.readouterr().out == (
        "| `type` | Purpose | Key fields |\n"
        "|---|---|---|\n"
        f"{_blocks_table_row('divider')}\n"
        "\n"
        "Fields\n"
        f"  span: int | null, default null. {span}\n"
    )


def test_the_guide_lookup_for_request_prints_row_section_and_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--guide", "request"])

    out = capsys.readouterr().out
    section = _guide_section("## The `request`")
    fields = out.split("\nFields\n", 1)[1]
    assert exit_code == 0
    assert out.startswith(
        "| `type` | Purpose | Key fields |\n"
        "|---|---|---|\n"
        f"{_blocks_table_row('request')}\n"
        "\n"
        f"{section}\n"
        "\n"
        "Fields\n"
    )
    field_lines = fields.splitlines()
    assert field_lines[0] == f"  span: int | null, default null. {Divider.model_fields['span'].description}"
    assert "  label: str, required. What the call is for, shown in the header." in field_lines
    assert (
        "  headers: dict[str, str], default {}. Request headers as a map, in the order they should read. "
        "A value may carry `{{variable}}` tokens."
    ) in field_lines
    assert (
        "  method: GET | POST | PUT | PATCH | DELETE | HEAD | OPTIONS | null, default null. "
        "The HTTP method. Required unless the call runs a `command`."
    ) in field_lines
    assert [line.split(":")[0].strip() for line in field_lines] == [
        "span",
        "variables",
        "id",
        "label",
        "method",
        "url",
        "command",
        "command_note",
        "headers",
        "body",
        "case_variable",
        "cases",
    ]


def test_the_listing_flag_prints_sections_and_blocks(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--guide", "--list"])

    out = capsys.readouterr().out
    sections, blocks = out.split("\n\nBlocks\n")
    assert exit_code == 0
    assert sections.startswith("Guide sections\nShape\n`meta`\n")
    assert "\nThe `request`\n" in sections
    assert blocks.splitlines()[:3] == ["heading", "text", "list"]
    assert blocks.splitlines() == list(block_names())


def test_a_guide_value_that_is_the_content_file_keeps_the_old_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = tmp_path / "report.yaml"
    content.write_text("version: 1\n", encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        main(["--guide", str(content)])

    assert raised.value.code == 2
    assert "--guide runs on its own; drop the content file" in capsys.readouterr().err


def test_an_unknown_block_on_the_command_line_fails_naming_the_valid_blocks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--guide", "gamma"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == f"error: unknown block 'gamma'; the blocks are {', '.join(block_names())}\n"


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
