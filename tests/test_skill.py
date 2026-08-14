import os
from pathlib import Path

import pytest

from skaldr.cli import install_plan_rule, install_skill, main, sync_installed_skills
from skaldr.models import load_report, package_path
from skaldr.render import render_html

_BUNDLED_SKALDR_SKILL = (package_path("skill") / "SKILL.md").read_bytes()


def _install(home: Path) -> Path:
    """Install the bundled skills into <home>/.claude and return the skaldr SKILL.md path."""
    (home / ".claude").mkdir(exist_ok=True)
    assert install_skill(home=home) == 0
    return home / ".claude" / "skills" / "skaldr" / "SKILL.md"


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


def test_install_brings_the_presentation_skill_alongside_the_primary(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()

    assert install_skill(home=tmp_path) == 0

    skills = tmp_path / ".claude" / "skills"
    assert (skills / "skaldr" / "SKILL.md").is_file()
    assert (skills / "skaldr-presentation" / "SKILL.md").is_file()  # each skill in its own folder
    assert (skills / "skaldr-reflect" / "SKILL.md").is_file()


def test_presentation_skill_covers_the_core_workflow() -> None:
    text = (package_path("skills/skaldr-presentation") / "SKILL.md").read_text(encoding="utf-8")

    assert "runbook.yaml" in text  # skaldr's real deliverable — the teleprompter
    assert "template" in text  # the deck goes into the org's real brand template, not skaldr
    assert "--check --strict" in text  # the pre-final placeholder gate


def test_reflect_skill_covers_its_workflow() -> None:
    text = (package_path("skills/skaldr-reflect") / "SKILL.md").read_text(encoding="utf-8")

    assert "skaldr --guide" in text  # check the guide first so it doesn't propose what already exists
    assert "Proposed fix" in text  # each pain point ends in a concrete, actionable fix
    assert "Ranked" in text or "rank" in text.lower()  # the output is impact-ranked


def test_every_bundled_skill_name_matches_its_install_folder() -> None:
    """Claude Code requires a skill's `name:` frontmatter to equal its folder. The primary skill
    installs to ~/.claude/skills/skaldr; each `skills/<dir>` installs to ~/.claude/skills/<dir>. Assert
    every bundled skill's `name:` matches the folder it lands in, so a new skill can't ship mismatched."""
    checks = [(package_path("skill") / "SKILL.md", "skaldr")]
    for skill_dir in package_path("skills").iterdir():
        if (skill_dir / "SKILL.md").is_file():
            checks.append((skill_dir / "SKILL.md", skill_dir.name))

    assert len(checks) >= 2  # primary + at least the presentation skill
    for skill_md, expected_name in checks:
        assert f"name: {expected_name}\n" in skill_md.read_text(encoding="utf-8")


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


def test_install_skill_leaves_a_symlinked_skill_file_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # a real dir with a symlinked SKILL.md (a contributor's live-edit link) — even an explicit install
    # must not write through the link and clobber the tracked source; it skips that one with a note
    dest_dir = tmp_path / ".claude" / "skills" / "skaldr"
    dest_dir.mkdir(parents=True)
    live_source = tmp_path / "repo-skill.md"
    live_source.write_text("# live-edit source\n", encoding="utf-8")
    (dest_dir / "SKILL.md").symlink_to(live_source)

    rc = install_skill(home=tmp_path)

    assert rc == 0
    assert (dest_dir / "SKILL.md").is_symlink()  # left as a link
    assert live_source.read_text(encoding="utf-8") == "# live-edit source\n"  # source unclobbered
    assert "leaving the symlinked skill file" in capsys.readouterr().out


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


_LEGACY_BEGIN = "<!-- skaldr:plan-rule - managed by `skaldr --install-skill`; delete this block to remove -->"


def test_install_plan_rule_replaces_a_block_written_with_a_legacy_marker(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    md_path = tmp_path / ".claude" / "CLAUDE.md"
    md_path.write_text(
        f"# Header\n\n{_LEGACY_BEGIN}\n# Working plans\n\nold guidance\n{_PLAN_RULE_END}\n",
        encoding="utf-8",
    )

    assert install_plan_rule(home=tmp_path) == 0

    claude_md = md_path.read_text(encoding="utf-8")
    assert claude_md.count(_PLAN_RULE_END) == 1
    assert _LEGACY_BEGIN not in claude_md
    assert "old guidance" not in claude_md
    assert "# Header" in claude_md


def test_install_plan_rule_collapses_blocks_left_by_two_marker_generations(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    md_path = tmp_path / ".claude" / "CLAUDE.md"
    md_path.write_text(
        f"# Header\n\n{_LEGACY_BEGIN}\nfirst generation\n{_PLAN_RULE_END}\n\n"
        f"{_PLAN_RULE_BEGIN}\nsecond generation\n{_PLAN_RULE_END}\n",
        encoding="utf-8",
    )

    assert install_plan_rule(home=tmp_path) == 0

    claude_md = md_path.read_text(encoding="utf-8")
    assert claude_md.count(_PLAN_RULE_END) == 1
    assert "first generation" not in claude_md
    assert "second generation" not in claude_md
    assert "# Header" in claude_md


def test_install_plan_rule_leaves_an_unpaired_legacy_marker_alone(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    md_path = tmp_path / ".claude" / "CLAUDE.md"
    md_path.write_text(f"# Header\n\n{_LEGACY_BEGIN}\nhalf-written\n\nreal content below\n", encoding="utf-8")

    assert install_plan_rule(home=tmp_path) == 0
    assert install_plan_rule(home=tmp_path) == 0

    claude_md = md_path.read_text(encoding="utf-8")
    assert "real content below" in claude_md
    assert claude_md.count(_PLAN_RULE_END) == 1


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
    assert "bundled skill(s) not found" in capsys.readouterr().err


def test_install_skill_reports_a_filesystem_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # ~/.claude exists but is a file, so mkdir of .claude/skills/skaldr raises NotADirectoryError —
    # it must surface as a clean CLI error, not an uncaught traceback.
    (tmp_path / ".claude").write_text("not a dir", encoding="utf-8")

    rc = install_skill(home=tmp_path)

    assert rc == 1
    assert "could not install the skill" in capsys.readouterr().err


# --- on-invoke skill self-sync (refresh already-installed skills after an upgrade) ---


def _enable_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest's autouse fixture disables sync for every test; these tests exercise the sync itself,
    # so clear the opt-out (they still target a tmp home, never the real ~/.claude).
    monkeypatch.delenv("SKALDR_SKILL_SYNC", raising=False)


def test_sync_refreshes_a_drifted_installed_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _enable_sync(monkeypatch)
    dest = _install(tmp_path)
    capsys.readouterr()  # drain the install output
    dest.write_text("# stale — an old shipped version\n", encoding="utf-8")

    sync_installed_skills(home=tmp_path)

    assert dest.read_bytes() == _BUNDLED_SKALDR_SKILL  # refreshed to the packaged copy
    assert "refreshed the 'skaldr' skill" in capsys.readouterr().err  # announced on stderr


def test_sync_is_a_no_op_and_silent_when_already_up_to_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _enable_sync(monkeypatch)
    dest = _install(tmp_path)  # freshly installed → identical to bundled
    capsys.readouterr()  # drain the install output
    os.utime(dest, (1_000_000, 1_000_000))  # pin an old mtime; a rewrite would bump it

    sync_installed_skills(home=tmp_path)

    assert dest.stat().st_mtime == 1_000_000  # no write happened
    assert capsys.readouterr().err == ""  # silent on a no-op (only prints when it refreshes)


def test_sync_skips_a_symlinked_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # a contributor live-edits by symlinking the skill dir into their checkout — sync must never clobber it
    _enable_sync(monkeypatch)
    skills = tmp_path / ".claude" / "skills"
    skills.mkdir(parents=True)
    live_edit = tmp_path / "repo-skill"
    live_edit.mkdir()
    (live_edit / "SKILL.md").write_text("# live-edit source\n", encoding="utf-8")
    (skills / "skaldr").symlink_to(live_edit, target_is_directory=True)

    sync_installed_skills(home=tmp_path)

    assert (skills / "skaldr").is_symlink()  # link untouched
    assert (live_edit / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "# live-edit source\n"  # source unclobbered


def test_sync_does_not_create_an_uninstalled_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ~/.claude/skills exists but skaldr isn't installed — a passive run must not auto-create it
    _enable_sync(monkeypatch)
    (tmp_path / ".claude" / "skills").mkdir(parents=True)

    sync_installed_skills(home=tmp_path)

    assert not (tmp_path / ".claude" / "skills" / "skaldr").exists()


def test_sync_short_circuits_when_skills_dir_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # no ~/.claude/skills at all → returns cleanly, creates nothing
    _enable_sync(monkeypatch)

    sync_installed_skills(home=tmp_path)

    assert not (tmp_path / ".claude").exists()


def test_sync_never_raises_when_the_claude_dir_is_unsearchable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a locked-down home: ~/.claude isn't searchable, so even stat-ing skills/ raises PermissionError.
    # The setup guard must swallow it — reaching the end of this test (no exception) is the assertion.
    _enable_sync(monkeypatch)
    claude = tmp_path / ".claude"
    (claude / "skills").mkdir(parents=True)
    claude.chmod(0o000)

    try:
        sync_installed_skills(home=tmp_path)  # must not raise
    finally:
        claude.chmod(0o755)  # restore so tmp cleanup can descend


def test_sync_never_raises_on_a_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_sync(monkeypatch)
    dest = _install(tmp_path)
    dest.write_text("# stale\n", encoding="utf-8")  # drifted → sync will try to rewrite
    dest.parent.chmod(0o555)  # read-only dir → the atomic write can't create its temp file

    try:
        sync_installed_skills(home=tmp_path)  # must swallow the PermissionError, not raise
        assert dest.read_text(encoding="utf-8") == "# stale\n"  # write failed, left as-is
    finally:
        dest.parent.chmod(0o755)  # restore so tmp cleanup can remove it


def test_sync_skips_a_symlinked_skill_file_in_a_real_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a subtler live-edit: the skill DIR is real but SKILL.md is symlinked into the checkout — the
    # atomic write would follow the link and clobber the tracked source, so sync must skip it
    _enable_sync(monkeypatch)
    dest_dir = tmp_path / ".claude" / "skills" / "skaldr"
    dest_dir.mkdir(parents=True)
    live_source = tmp_path / "repo-skill.md"
    live_source.write_text("# live-edit source\n", encoding="utf-8")
    (dest_dir / "SKILL.md").symlink_to(live_source)

    sync_installed_skills(home=tmp_path)

    assert (dest_dir / "SKILL.md").is_symlink()  # link untouched
    assert live_source.read_text(encoding="utf-8") == "# live-edit source\n"  # source unclobbered


def test_sync_isolates_a_failing_skill_from_the_rest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # one skill's write failing must not abort refreshing the others — the loop is per-skill fail-safe
    _enable_sync(monkeypatch)
    _install(tmp_path)
    skaldr_dir = tmp_path / ".claude" / "skills" / "skaldr"  # first in _BUNDLED_SKILLS
    reflect_file = tmp_path / ".claude" / "skills" / "skaldr-reflect" / "SKILL.md"  # later in the list
    (skaldr_dir / "SKILL.md").write_text("# stale\n", encoding="utf-8")
    reflect_file.write_text("# stale\n", encoding="utf-8")
    skaldr_dir.chmod(0o555)  # skaldr's refresh will fail

    try:
        sync_installed_skills(home=tmp_path)
        assert (skaldr_dir / "SKILL.md").read_text(encoding="utf-8") == "# stale\n"  # skaldr failed
        # …but the later skill still refreshed, proving the failure didn't abort the loop
        assert reflect_file.read_bytes() == (package_path("skills/skaldr-reflect") / "SKILL.md").read_bytes()
    finally:
        skaldr_dir.chmod(0o755)


def test_sync_is_disabled_by_the_opt_out_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = _install(tmp_path)
    dest.write_text("# stale\n", encoding="utf-8")
    monkeypatch.setenv("SKALDR_SKILL_SYNC", "0")

    sync_installed_skills(home=tmp_path)

    assert dest.read_text(encoding="utf-8") == "# stale\n"  # opt-out → left drifted


def test_install_skill_is_update_only_and_does_not_rewrite_a_current_skill(tmp_path: Path) -> None:
    dest = _install(tmp_path)
    os.utime(dest, (1_000_000, 1_000_000))

    assert install_skill(home=tmp_path) == 0  # re-run on an up-to-date install

    assert dest.stat().st_mtime == 1_000_000  # clean no-op: no rewrite


def test_main_refreshes_a_drifted_skill_on_a_normal_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the wiring: a plain `skaldr report.yaml` run refreshes a drifted installed skill (via main()'s
    # top-of-run sync) — home is redirected to a tmp dir so the real ~/.claude is never touched.
    _enable_sync(monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # sync's default home → tmp, not real ~/.claude
    dest = _install(tmp_path)
    dest.write_text("# stale\n", encoding="utf-8")
    report = tmp_path / "r.yaml"
    report.write_text("version: 1\nmeta: {title: T}\nblocks: [{type: text, body: hi}]\n", encoding="utf-8")

    assert main([str(report), "-o", str(tmp_path / "r.html")]) == 0

    assert dest.read_bytes() == _BUNDLED_SKALDR_SKILL  # main()'s sync refreshed it
