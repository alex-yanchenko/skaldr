"""CLI entry point: render a content file, print the guide, export the schema, or install the skill."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from skaldr.errors import ReportError
from skaldr.models import Report, load_report, package_path, package_text
from skaldr.pdf import html_to_pdf
from skaldr.render import render_file, render_html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a skaldr content file to an HTML page.")
    parser.add_argument("data", nargs="?", help="path to the content YAML")
    parser.add_argument("-o", "--out", help="output HTML path (default: out/<data-stem>.html)")
    parser.add_argument(
        "--embed",
        action="store_true",
        help="emit an Artifact-ready fragment (inline <style> + content, no <html>/<head>/<body> "
        "skeleton or scripts) for publishing to a claude.ai Artifact, instead of a full document",
    )
    parser.add_argument(
        "--pdf",
        metavar="PATH",
        help="render straight to a PDF at PATH (drives a headless Chrome/Chromium/Edge — needs one "
        "installed; set SKALDR_BROWSER to override discovery). Prints the full page's print styling.",
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

    if not args.data:
        parser.error("a content file is required (or use --write-schema)")

    data_path = Path(args.data).resolve()
    written: list[Path] = []
    try:
        report = load_report(data_path)
        if args.pdf:
            # PDF always prints the full page (the print CSS needs the whole document, not a fragment).
            pdf_path = Path(args.pdf).resolve()
            html_to_pdf(render_html(report), pdf_path)
            written.append(pdf_path)
        # Write HTML when asked (-o), or by default when no --pdf was requested.
        if args.out or not args.pdf:
            out_path = Path(args.out).resolve() if args.out else Path.cwd() / "out" / f"{data_path.stem}.html"
            render_file(data_path, out_path, embed=args.embed)
            written.append(out_path)
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(f"OK  {path}")
    print(f"    {_plural(len(report.blocks), 'block')}, {_plural(len(report.badges), 'badge')}")
    return 0


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
