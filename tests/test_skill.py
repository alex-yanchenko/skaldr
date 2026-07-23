from pathlib import Path

import pytest

from skaldr.cli import install_plan_rule, install_skill, main
from skaldr.models import load_report, package_path
from skaldr.render import render_html

# The frozen CLAUDE.md managed-block delimiters — a user-facing contract (the block the README tells
# users to delete). Held as literals so the tests don't reach for module-private names in cli.py.
_PLAN_RULE_BEGIN = (
    "<!-- skaldr:plan-rule - managed by `skaldr --install-plan-rule`; delete this block to remove -->"
)
_PLAN_RULE_END = "<!-- /skaldr:plan-rule -->"


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
    # Thinness backstop. The structural asserts above are the real guard (no block catalog); this
    # cap just stops the file doubling. The description carries a palette routing-signal plus the
    # when-to-use / destination boundary, so it sits well above a bare frontmatter — a block catalog
    # would still blow past this.
    assert len(skill_md) < 4000


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


def test_install_skill_does_not_touch_claude_md(tmp_path: Path) -> None:
    # The split: --install-skill copies the skill only; it must never create or edit CLAUDE.md.
    (tmp_path / ".claude").mkdir()

    assert install_skill(home=tmp_path) == 0

    assert (tmp_path / ".claude" / "skills" / "skaldr" / "SKILL.md").is_file()
    assert not (tmp_path / ".claude" / "CLAUDE.md").exists()


def test_install_plan_rule_adds_the_rule_to_claude_md(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".claude").mkdir()

    rc = install_plan_rule(home=tmp_path)

    out = capsys.readouterr().out
    claude_md = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert rc == 0
    assert "Working plans as live skaldr docs" in claude_md
    assert "compaction-proof" in claude_md  # a line countering the "shareable-only" misconception
    assert "skaldr:plan-rule" in claude_md  # delimited by the managed markers
    assert "added the plan-workflow rule" in out  # a fresh install reports it as added


def test_install_plan_rule_does_not_install_the_skill(tmp_path: Path) -> None:
    # The other half of the split: --install-plan-rule writes CLAUDE.md only, never the skill dir.
    (tmp_path / ".claude").mkdir()

    assert install_plan_rule(home=tmp_path) == 0

    assert (tmp_path / ".claude" / "CLAUDE.md").is_file()
    assert not (tmp_path / ".claude" / "skills" / "skaldr").exists()


def test_install_plan_rule_advises_when_claude_is_not_set_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = install_plan_rule(home=tmp_path)

    assert rc == 0
    assert not (tmp_path / ".claude").exists()
    assert "Claude Code doesn't appear to be set up" in capsys.readouterr().out


def test_install_plan_rule_is_idempotent_and_preserves_existing_content(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    md_path = tmp_path / ".claude" / "CLAUDE.md"
    md_path.write_text("# My global rules\n\nkeep this line.\n", encoding="utf-8")

    assert install_plan_rule(home=tmp_path) == 0
    assert install_plan_rule(home=tmp_path) == 0  # a second install must not duplicate the block

    claude_md = md_path.read_text(encoding="utf-8")
    assert "keep this line." in claude_md  # pre-existing content untouched
    assert claude_md.count("Working plans as live skaldr docs") == 1  # exactly one managed block


def test_install_plan_rule_refreshes_the_block_in_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".claude").mkdir()
    md_path = tmp_path / ".claude" / "CLAUDE.md"
    install_plan_rule(home=tmp_path)
    # simulate a stale prior install by mangling the managed block's body
    md_path.write_text(
        md_path.read_text(encoding="utf-8").replace("compaction-proof", "STALE"), encoding="utf-8"
    )

    install_plan_rule(home=tmp_path)  # re-install refreshes the block in place

    refreshed = md_path.read_text(encoding="utf-8")
    assert "updated the plan-workflow rule" in capsys.readouterr().out  # reported as a refresh
    assert "STALE" not in refreshed  # the old block was replaced, not left alongside
    assert "compaction-proof" in refreshed
    assert refreshed.count("Working plans as live skaldr docs") == 1


def test_install_plan_rule_places_existing_content_before_the_block(tmp_path: Path) -> None:
    # The managed block must be appended AFTER the user's own content, never prepended over it.
    (tmp_path / ".claude").mkdir()
    md_path = tmp_path / ".claude" / "CLAUDE.md"
    md_path.write_text("# My global rules\n\nkeep this line.\n", encoding="utf-8")

    assert install_plan_rule(home=tmp_path) == 0

    claude_md = md_path.read_text(encoding="utf-8")
    assert claude_md.index("keep this line.") < claude_md.index(_PLAN_RULE_BEGIN)


def test_install_plan_rule_never_builds_on_an_unpaired_marker(tmp_path: Path) -> None:
    # A hand-edited/partial CLAUDE.md with a lone BEGIN (no END) must not be treated as a managed
    # block: content after the stray marker must survive a re-install, not be swallowed.
    (tmp_path / ".claude").mkdir()
    md_path = tmp_path / ".claude" / "CLAUDE.md"
    md_path.write_text(
        f"# Header\n\n{_PLAN_RULE_BEGIN}\nhalf-written\n\nreal content below\n", encoding="utf-8"
    )

    assert install_plan_rule(home=tmp_path) == 0
    assert install_plan_rule(home=tmp_path) == 0  # the second run is where a naive parser eats content

    claude_md = md_path.read_text(encoding="utf-8")
    assert "real content below" in claude_md
    assert claude_md.count(_PLAN_RULE_END) == 1  # exactly one complete managed block


def test_install_plan_rule_reports_a_claude_md_write_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # CLAUDE.md is a directory, so the rule write raises OSError — the error must name CLAUDE.md.
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").mkdir()

    rc = install_plan_rule(home=tmp_path)

    err = capsys.readouterr().err
    assert rc == 1
    assert "could not update" in err
    assert "CLAUDE.md" in err


def test_install_plan_rule_leaves_claude_md_intact_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A mid-write failure (disk full) must not truncate the user's CLAUDE.md: the atomic temp-then-swap
    # means the original survives untouched when the write raises.
    (tmp_path / ".claude").mkdir()
    md_path = tmp_path / ".claude" / "CLAUDE.md"
    md_path.write_text("precious content\n", encoding="utf-8")
    real_write_text = Path.write_text

    def failing_write_text(self: Path, *args: object, **kwargs: object) -> int:
        if self.name.endswith(".skaldr-tmp"):
            raise OSError("No space left on device")
        return real_write_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    rc = install_plan_rule(home=tmp_path)

    assert rc == 1
    assert md_path.read_text(encoding="utf-8") == "precious content\n"  # untouched, not truncated


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
