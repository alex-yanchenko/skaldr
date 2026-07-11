from pathlib import Path

import pytest

from skaldr.cli import install_skill, main
from skaldr.models import load_report, package_path
from skaldr.render import render_html


def test_skill_ships_the_thin_skill_guide_and_example() -> None:
    skill = package_path("skill")

    assert (skill / "SKILL.md").is_file()
    assert (skill / "GUIDE.md").is_file()
    assert (skill / "example.yaml").is_file()


def test_skill_md_is_thin_and_defers_to_the_tool() -> None:
    """The installed SKILL.md must stay version-agnostic — it points at `skaldr --guide` rather
    than restating the block catalog (which would drift across versions)."""
    skill_md = (package_path("skill") / "SKILL.md").read_text(encoding="utf-8")

    assert "skaldr --guide" in skill_md
    assert "## Blocks" not in skill_md
    assert "| `heading` |" not in skill_md
    assert len(skill_md) < 2000


def test_guide_command_prints_the_authoring_guide_and_example(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--guide"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "## Blocks" in out  # a guide section
    assert "| `heading` |" in out  # the block catalog
    # The appended example — assert on text that lives ONLY in example.yaml, so this proves the
    # concatenation happened (the guide body alone already contains strings like "version: 1").
    assert "## A complete example" in out
    assert "The 600 double-counts clear with the de-dup fix" in out


def test_skill_example_renders_with_its_reconciliation_balanced() -> None:
    html = render_html(load_report(package_path("skill") / "example.yaml"))

    assert html.startswith("<!doctype html>")
    assert "Reconciles: 1,500 + 8,500 matched cleanly = 10,000." in html


def test_install_skill_copies_the_thin_skill_as_a_real_file(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()

    rc = install_skill(home=tmp_path)

    dest = tmp_path / ".claude" / "skills" / "skaldr" / "SKILL.md"
    src = package_path("skill") / "SKILL.md"
    assert rc == 0
    assert dest.is_file()
    assert not dest.is_symlink()  # a copy, not a link into the versioned install
    assert dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_install_skill_is_idempotent(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()

    assert install_skill(home=tmp_path) == 0
    assert install_skill(home=tmp_path) == 0
    assert (tmp_path / ".claude" / "skills" / "skaldr" / "SKILL.md").is_file()


def test_install_skill_migrates_an_older_symlinked_install(tmp_path: Path) -> None:
    elsewhere = tmp_path / "old-cellar-skill"
    elsewhere.mkdir()
    skills = tmp_path / ".claude" / "skills"
    skills.mkdir(parents=True)
    (skills / "skaldr").symlink_to(elsewhere, target_is_directory=True)

    rc = install_skill(home=tmp_path)

    dest_dir = skills / "skaldr"
    src = package_path("skill") / "SKILL.md"
    assert rc == 0
    assert not dest_dir.is_symlink()  # migrated to a real dir
    assert (dest_dir / "SKILL.md").read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_install_skill_preserves_other_files_in_the_dir(tmp_path: Path) -> None:
    # Copy-install merges SKILL.md into the dir; it must not delete a co-located file (the new
    # contract that replaced the old "refuse if occupied" behaviour).
    dest_dir = tmp_path / ".claude" / "skills" / "skaldr"
    dest_dir.mkdir(parents=True)
    (dest_dir / "keep.txt").write_text("mine", encoding="utf-8")

    rc = install_skill(home=tmp_path)

    assert rc == 0
    assert (dest_dir / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert (dest_dir / "SKILL.md").is_file()


def test_install_skill_reports_error_when_dest_is_a_plain_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills = tmp_path / ".claude" / "skills"
    skills.mkdir(parents=True)
    (skills / "skaldr").write_text("debris", encoding="utf-8")  # a file where the skill dir should be

    rc = install_skill(home=tmp_path)

    assert rc == 1
    assert "could not install the skill" in capsys.readouterr().err


def test_install_skill_advises_with_cp_when_claude_is_not_set_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = install_skill(home=tmp_path)

    out = capsys.readouterr().out
    src = package_path("skill") / "SKILL.md"
    dest_dir = tmp_path / ".claude" / "skills" / "skaldr"
    assert rc == 0
    assert not (tmp_path / ".claude").exists()
    assert "Claude Code doesn't appear to be set up" in out
    assert f"mkdir -p {dest_dir}" in out
    assert f"cp {src} {dest_dir}/" in out


def test_install_skill_reports_a_missing_bundled_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing_skill(_name: str) -> Path:
        return tmp_path / "no-skill-here"

    monkeypatch.setattr("skaldr.cli.package_path", missing_skill)

    rc = install_skill(home=tmp_path)

    assert rc == 1
    assert "bundled skill not found" in capsys.readouterr().err


def test_install_skill_reports_a_filesystem_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # ~/.claude exists but is a file, so mkdir of .claude/skills/skaldr raises NotADirectoryError —
    # it must surface as a clean CLI error, not an uncaught traceback.
    (tmp_path / ".claude").write_text("not a dir", encoding="utf-8")

    rc = install_skill(home=tmp_path)

    assert rc == 1
    assert "could not install the skill" in capsys.readouterr().err
