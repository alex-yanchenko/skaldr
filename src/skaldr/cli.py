"""CLI entry point: render a content file (once or on a --watch loop), validate it (--check), dump its
normalised model (--emit-json), print the guide, export the schema, or install the skill."""

import argparse
import json
import shutil
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from skaldr.errors import ReportError
from skaldr.models import Report, load_report, package_path, package_text
from skaldr.pdf import html_to_pdf
from skaldr.render import render_html, render_report

_POLL_INTERVAL_SECONDS = 0.4  # how often --watch re-stats the content file for changes


def _resolve_out_path(data_path: Path, out_arg: str | None) -> Path:
    """The HTML output path: the explicit `-o` value, or a default `out/<data-stem>.html` under the cwd."""
    return Path(out_arg).resolve() if out_arg else Path.cwd() / "out" / f"{data_path.stem}.html"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a skaldr content file to an HTML page.")
    parser.add_argument(
        "data",
        nargs="*",
        help="path to the content YAML (one to render; one or more with --check)",
    )
    parser.add_argument("-o", "--out", help="output HTML path (default: out/<data-stem>.html)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the content file(s) against the schema and exit — no HTML written. Pass several "
        "(e.g. a glob) to validate a whole set; exits non-zero if any file is invalid.",
    )
    parser.add_argument(
        "--emit-json",
        action="store_true",
        help="validate the content file and print its normalised model as JSON to stdout (no HTML) — "
        "for tooling/an agent to query the data without re-parsing YAML + markdown.",
    )
    parser.add_argument(
        "--embed",
        action="store_true",
        help="emit an Artifact-ready fragment (inline <style> + content + controls, no "
        "<html>/<head>/<body> skeleton or CSP meta) for publishing to a claude.ai Artifact, "
        "instead of a full document",
    )
    parser.add_argument(
        "--pdf",
        metavar="PATH",
        help="render straight to a PDF at PATH (drives a headless Chrome/Chromium/Edge — needs one "
        "installed; set SKALDR_BROWSER to override discovery). Prints the full page's print styling.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="re-render to HTML on every save of the content file — a live edit-preview loop; Ctrl-C to "
        "stop. HTML only; can't combine with --check/--emit-json/--pdf. (Watches the file itself, not "
        "its !include fragments.)",
    )
    parser.add_argument(
        "--write-schema",
        metavar="PATH",
        help="write the JSON Schema for content files to PATH and exit",
    )
    parser.add_argument(
        "--guide",
        action="store_true",
        help="print the authoring guide (blocks, rules, a complete example) and exit",
    )
    parser.add_argument(
        "--install-skill",
        action="store_true",
        help="install skaldr's Claude skill into ~/.claude/skills (copies it — run once, survives "
        "upgrades), then exit",
    )
    args = parser.parse_args(argv)

    if args.install_skill:
        return install_skill()

    if args.guide:
        try:
            print(_guide_text())
        except OSError as err:
            print(f"error: could not read the bundled guide: {err}", file=sys.stderr)
            return 1
        return 0

    if args.write_schema:
        schema_path = Path(args.write_schema)
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.write_text(json.dumps(Report.model_json_schema(), indent=2) + "\n", encoding="utf-8")
        print(f"OK  {schema_path}")
        return 0

    # --check and --emit-json are validate-only: they never write, so an output flag is a silent no-op.
    if args.check and args.emit_json:
        parser.error("--check and --emit-json are mutually exclusive (each is a distinct validate-only mode)")
    if (args.check or args.emit_json) and (args.out or args.pdf or args.embed):
        parser.error("--check/--emit-json only validate — they write no HTML, so -o/--pdf/--embed do nothing")
    if args.watch and (args.check or args.emit_json or args.pdf):
        parser.error("--watch re-renders HTML on change; it can't combine with --check/--emit-json/--pdf")

    if args.check:
        if not args.data:
            parser.error("--check needs at least one content file")
        return _check_files(args.data)

    if not args.data:
        parser.error("a content file is required (or use --write-schema)")
    if len(args.data) > 1:
        parser.error("only one content file can be processed at a time (use --check to validate several)")

    data_path = Path(args.data[0]).resolve()

    if args.watch:
        return _watch(data_path, _resolve_out_path(data_path, args.out), embed=args.embed)

    if args.emit_json:
        try:
            report = load_report(data_path)
        except ReportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(report.model_dump(mode="json"), indent=2))
        return 0
    # --embed only shapes HTML output; with --pdf and no -o no HTML is written, so it would be inert.
    if args.embed and args.pdf and not args.out:
        parser.error(
            "--embed has no effect with --pdf alone (no HTML is written); add -o to also "
            "write the embed fragment, or drop --embed"
        )
    written: list[Path] = []
    try:
        report = load_report(data_path)
        # HTML first — it needs no browser, so a later PDF failure never costs the reader the HTML.
        # Write HTML when asked (-o), or by default when no --pdf was requested.
        if args.out or not args.pdf:
            out_path = _resolve_out_path(data_path, args.out)
            render_report(report, out_path, embed=args.embed)
            written.append(out_path)
        if args.pdf:
            # PDF prints the full page with every section expanded: the print CSS needs the whole
            # document (not a fragment), and headless print can't rely on the beforeprint script.
            pdf_path = Path(args.pdf).resolve()
            html_to_pdf(render_html(report, expand=True), pdf_path)
            written.append(pdf_path)
    except (ReportError, OSError) as exc:
        for path in written:
            print(f"OK  {path}")
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(f"OK  {path}")
    print(f"    {_plural(len(report.blocks), 'block')}, {_plural(len(report.badges), 'badge')}")
    return 0


def _render_once(data_path: Path, out_path: Path, *, embed: bool) -> int:
    """Render the content file to HTML once. Returns 0 on success, 1 on a load/render error (printed) —
    it never raises, so the --watch loop survives an invalid mid-edit save."""
    try:
        report = load_report(data_path)
        render_report(report, out_path, embed=embed)
    except Exception as exc:
        # Resilience boundary: any render failure prints and keeps the --watch loop alive. Catching
        # Exception (not BaseException) still lets a Ctrl-C KeyboardInterrupt propagate to the loop.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"OK  {out_path}")
    print(f"    {_plural(len(report.blocks), 'block')}, {_plural(len(report.badges), 'badge')}")
    return 0


def _mtime(path: Path) -> float | None:
    """The file's modification time, or None if it's momentarily missing (mid-save/rename)."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _watch(data_path: Path, out_path: Path, *, embed: bool, interval: float = _POLL_INTERVAL_SECONDS) -> int:
    """Re-render to HTML whenever the content file changes, until interrupted. Polls the mtime (no
    third-party watcher); a failing render prints its error and the loop keeps going."""
    print(f"watching {data_path} — re-rendering to {out_path} on change (Ctrl-C to stop)")
    try:
        _render_once(data_path, out_path, embed=embed)
        last = _mtime(data_path)
        while True:
            time.sleep(interval)
            current = _mtime(data_path)
            if current is not None and current != last:
                last = current
                print(f"\n{data_path} changed — re-rendering:")
                _render_once(data_path, out_path, embed=embed)
    except KeyboardInterrupt:
        print("\nstopped watching")
        return 0


def _check_files(paths: Sequence[str]) -> int:
    """Validate each content file against the schema without rendering. Prints one line per file and
    returns 1 if any file is invalid, so it drops straight into a pre-commit hook or CI over a glob."""
    failed = 0
    for raw_path in paths:
        path = Path(raw_path)
        try:
            load_report(path)
        except ReportError as exc:
            failed += 1
            print(f"FAIL  {path}: {exc}", file=sys.stderr)
        else:
            print(f"OK    {path}")
    if failed:
        print(f"\n{_plural(failed, 'file')} failed", file=sys.stderr)
    return 1 if failed else 0


def _guide_text() -> str:
    """The authoring guide (GUIDE.md) with the live, tested example appended — printed by --guide."""
    guide = package_text("skill/GUIDE.md").rstrip()
    example = package_text("skill/example.yaml").rstrip()
    return f"{guide}\n\n## A complete example\n\n```yaml\n{example}\n```"


def install_skill(home: Path | None = None) -> int:
    """Copy the bundled skill (a thin, version-agnostic SKILL.md) into <home>/.claude/skills/skaldr.
    Because it's a copy of a stable file — not a link into the versioned install — it runs ONCE and
    survives upgrades; the version-specific detail is fetched at author time via `skaldr --guide` /
    `--write-schema`. Migrates an older symlinked install; advises if ~/.claude is absent."""
    if home is None:
        home = Path.home()
    src = package_path("skill") / "SKILL.md"
    if not src.is_file():
        print("error: bundled skill not found in this install", file=sys.stderr)
        return 1

    claude_dir = home / ".claude"
    dest_dir = claude_dir / "skills" / "skaldr"
    if not claude_dir.exists():
        print("Claude Code doesn't appear to be set up (~/.claude is missing).")
        print("If you use Claude Code, copy the skill in yourself:")
        print(f"    mkdir -p {dest_dir}")
        print(f"    cp {src} {dest_dir}/")
        return 0

    try:
        if dest_dir.is_symlink():
            print(f"note: migrating an older symlinked install at {dest_dir}")
            dest_dir.unlink()  # older skaldr symlinked this dir into the versioned install
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest_dir / "SKILL.md")
    except OSError as err:
        print(f"error: could not install the skill into {dest_dir}: {err}", file=sys.stderr)
        return 1
    print(f"OK  installed skaldr skill -> {dest_dir / 'SKILL.md'}")
    print("    Restart Claude Code (or reload skills) to pick it up.")
    return 0


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


if __name__ == "__main__":
    sys.exit(main())
