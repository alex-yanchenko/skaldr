import re
from pathlib import Path

import pytest

from skaldr.cli import main
from skaldr.guide_lookup import lookup
from skaldr.models import package_text, parse_report
from skaldr.render import find_placeholders
from tests.factories import make_report

GUIDE = package_text("skill/GUIDE.md")
STARTER = package_text("skill/plan-starter.yaml")
STARTER_PLACEHOLDERS = (
    "date, decision-one, decision-two, finished-step, first-action, mistake-to-avoid, one-line-summary, "
    "plan-title, reason-one, reason-two, second-action, step-in-progress, step-not-started, "
    "step-waiting-on-something, what-done-looks-like-and-why-it-matters"
)
GUIDE_STARTER_SECTION = re.compile(r"^## Working plan starter\n(.*?)(?=^## |\Z)", re.DOTALL | re.MULTILINE)
FENCED_YAML = re.compile(r"```yaml\n(.*?)```", re.DOTALL)


def _starter_file(tmp_path: Path) -> Path:
    path = tmp_path / "plan-starter.yaml"
    path.write_text(STARTER, encoding="utf-8")
    return path


def test_the_starter_builds_as_it_is(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _starter_file(tmp_path)

    exit_code = main(["--check", str(path)])

    assert (exit_code, capsys.readouterr().out) == (
        0,
        f"OK    {path}  (15 unfilled placeholders: {STARTER_PLACEHOLDERS})\n",
    )


def test_the_starter_fails_the_strict_check_naming_every_placeholder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _starter_file(tmp_path)

    exit_code = main(["--check", "--strict", str(path)])

    captured = capsys.readouterr()
    assert (exit_code, captured.out, captured.err) == (
        1,
        "",
        f"FAIL  {path}: 15 unfilled placeholders: {STARTER_PLACEHOLDERS}\n\n1 file failed\n",
    )


def test_the_guide_section_holds_the_starter_byte_for_byte() -> None:
    section = GUIDE_STARTER_SECTION.search(GUIDE)
    assert section is not None

    assert FENCED_YAML.findall(section.group(1)) == [STARTER]


def test_guide_plan_resolves_to_the_working_plan_starter_section_only() -> None:
    section = GUIDE_STARTER_SECTION.search(GUIDE)
    assert section is not None

    assert lookup("plan", GUIDE) == f"## Working plan starter\n{section.group(1)}".rstrip()


def test_new_plan_writes_the_starter_and_names_the_next_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "docs" / "plan.yaml"

    exit_code = main(["new", "plan", str(target)])

    assert (exit_code, capsys.readouterr().out, target.read_text(encoding="utf-8")) == (
        0,
        f"OK  wrote the plan starter to {target}\n"
        f"    fill in every {{{{placeholder}}}}, then render it: "
        f"skaldr {target} -o {target.with_suffix('.html')} --live\n",
        STARTER,
    )


def test_new_plan_refuses_a_file_that_exists_and_leaves_it_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "plan.yaml"
    target.write_text("mine", encoding="utf-8")

    exit_code = main(["new", "plan", str(target)])

    captured = capsys.readouterr()
    assert (exit_code, captured.out, captured.err, target.read_text(encoding="utf-8")) == (
        1,
        "",
        f"error: {target} already exists; pick another file name or delete it first\n",
        "mine",
    )


def test_new_with_an_unknown_kind_lists_the_valid_kinds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "x.yaml"

    exit_code = main(["new", "report", str(target)])

    captured = capsys.readouterr()
    assert (exit_code, captured.out, captured.err, target.exists()) == (
        1,
        "",
        "error: unknown kind 'report' for `skaldr new`; the kinds are plan\n",
        False,
    )


@pytest.mark.parametrize("arguments", [["new"], ["new", "plan"], ["new", "plan", "a.yaml", "b.yaml"]])
def test_new_without_exactly_a_kind_and_a_file_prints_its_usage(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(arguments)

    captured = capsys.readouterr()
    assert (exit_code, captured.out, captured.err) == (
        1,
        "",
        "error: usage: skaldr new <kind> <file>; the kinds are plan\n",
    )


def test_placeholders_in_the_title_subtitle_date_and_updated_are_unfilled_blanks() -> None:
    report = parse_report(
        make_report(
            meta={
                "title": "{{plan-title}}",
                "subtitle": ["{{first-line}}", "kept as written", "{{second-line}}"],
                "date": "{{when}}",
                "updated": "{{refreshed}}",
            }
        )
    )

    assert find_placeholders(report) == ["first-line", "plan-title", "refreshed", "second-line", "when"]


def test_a_document_with_no_placeholders_has_no_unfilled_blanks() -> None:
    report = parse_report(
        make_report(meta={"title": "Plain", "subtitle": ["a line"], "date": "Q3", "updated": "today"})
    )

    assert find_placeholders(report) == []
