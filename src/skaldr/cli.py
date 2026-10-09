"""CLI entry point: render a content file (once, only when stale, or on a --watch loop), validate it
(--check), export it as Markdown (--export), dump its normalised model (--emit-json), print the
guide, export the schema, or install the skill."""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from typing_extensions import assert_never

from skaldr.errors import PageFetchError, ReportError, UnknownGuideTopicError
from skaldr.export import EXPORT_MANIFEST, EXPORT_TARGETS, ExportTarget, export_markdown, export_notion
from skaldr.guide_lookup import is_topic, list_topics, lookup
from skaldr.models import Report, content_files, load_report, package_path, package_text
from skaldr.pdf import html_to_pdf
from skaldr.render import (
    RecordedRender,
    RenderOptions,
    extract_source,
    find_placeholders,
    recorded_render,
    render_html,
    render_report,
)
from skaldr.replace_file import replace_file, resolved_path
from skaldr.version import skaldr_version

_FETCH_TIMEOUT_SECONDS = 30
_FETCH_LIMIT_BYTES = 16 * 1024 * 1024
_FETCH_CHUNK_BYTES = 64 * 1024
_POLL_INTERVAL_SECONDS = 0.4  # how often --watch re-stats the content file for changes


# Markers delimiting skaldr's managed plan-workflow block inside the user's CLAUDE.md. ASCII only —
# they're matched by `re`/string ops on every re-install, so no fragile non-ASCII in the anchor.
_PLAN_RULE_BEGIN = (
    "<!-- skaldr:plan-rule - managed by `skaldr --install-plan-rule`; delete this block to remove -->"
)
_PLAN_RULE_END = "<!-- /skaldr:plan-rule -->"
# Match one COMPLETE block only. The tempered body `(?:(?!BEGIN|END).)*` refuses to span another
# marker, so a stray unpaired BEGIN can never pair with a later block's END and swallow the user's
# content between them — the rule body itself never contains a marker, so this stays exact.
_PLAN_RULE_BEGIN_ANY_VERSION = r"<!-- skaldr:plan-rule\b[^\n]*-->"
_PLAN_RULE_BLOCK = re.compile(
    _PLAN_RULE_BEGIN_ANY_VERSION
    + r"(?:(?!"
    + _PLAN_RULE_BEGIN_ANY_VERSION
    + r"|"
    + re.escape(_PLAN_RULE_END)
    + r").)*"
    + re.escape(_PLAN_RULE_END)
    + r"\n?",
    re.DOTALL,
)


def _resolve_out_path(data_path: Path, out_arg: str | None) -> Path:
    """The HTML output path: the explicit `-o` value, or a default `out/<data-stem>.html` under the cwd."""
    return resolved_path(Path(out_arg)) if out_arg else Path.cwd() / "out" / f"{data_path.stem}.html"


_STANDALONE_MODES = frozenset(
    {"write_schema", "guide", "install_skill", "install_plan_rule", "extract_source"}
)


def _flag_name(dest: str) -> str:
    return "the content file" if dest == "data" else "--" + dest.replace("_", "-")


def _return_a_swallowed_content_file(args: argparse.Namespace) -> None:
    value = args.guide
    if isinstance(value, str) and Path(value).is_file() and not is_topic(value, _guide_source()):
        args.data = [value, *args.data]
        args.guide = True


def _refuse_a_list_without_the_whole_guide(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.list and args.guide is not True:
        parser.error("--list lists the guide; use it as `--guide --list`")


def _refuse_company_for_a_standalone_mode(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    defaults = vars(parser.parse_args([]))
    given = [dest for dest, value in vars(args).items() if value != defaults[dest]]
    mode = next((dest for dest in given if dest in _STANDALONE_MODES), None)
    if mode is None:
        return
    others = [_flag_name(dest) for dest in given if dest != mode and not (mode == "guide" and dest == "list")]
    if others:
        parser.error(f"{_flag_name(mode)} runs on its own; drop {', '.join(others)}")


def _writes_an_html_page(args: argparse.Namespace) -> bool:
    if args.emit_json or args.export:
        return False
    if args.out or args.watch:
        return True
    if args.pdf:
        return False
    return not args.check or args.embed


def _run_auth(argv: list[str]) -> int:
    try:
        from skaldr.auth.cli import main as auth_main
    except ModuleNotFoundError as exc:
        missing = (exc.name or "skaldr").partition(".")[0]
        if missing == "skaldr":
            raise
        print(
            f"error: `skaldr auth` needs the publish extra ({missing} is not installed). Reinstall with it: "
            "uv tool install --force 'skaldr[publish]', pipx install --force 'skaldr[publish]', "
            "or pip install 'skaldr[publish]'",
            file=sys.stderr,
        )
        return 1
    return auth_main(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments[:1] == ["auth"]:
        return _run_auth(arguments[1:])
    parser = argparse.ArgumentParser(
        description="Render a skaldr content file to an HTML page.",
        epilog="Sign in to Notion or Jira with `skaldr auth`; see `skaldr auth --help`.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"skaldr {skaldr_version()}",
        help="print the installed skaldr version and exit",
    )
    parser.add_argument(
        "data",
        nargs="*",
        default=[],
        help="path to the content YAML (one to render; one or more with --check)",
    )
    parser.add_argument("-o", "--out", help="output HTML path (default: out/<data-stem>.html)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the content file(s) against the schema; exits non-zero if any file is invalid. "
        "Pass several (e.g. a glob) to validate a whole set, or add -o/--pdf/--embed/--export to one "
        "file to render it once it passes. A file that fails is never written.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="with --check: also fail if any `{{placeholder}}` blank is still unfilled: the "
        "finalize gate for a rehearse-then-finalize living doc.",
    )
    parser.add_argument(
        "--emit-json",
        action="store_true",
        help="validate the content file and print its normalised model as JSON to stdout (no HTML), "
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
        "--no-source",
        action="store_true",
        help="don't embed the YAML source in the rendered page (by default a full page and an --embed "
        "fragment both carry their own source so `skaldr --extract-source` can recover it)",
    )
    parser.add_argument(
        "--extract-source",
        metavar="FILE|URL",
        help="print the YAML source embedded in a rendered skaldr page (a local file or an http(s) URL) "
        "and exit, recovering the source without parsing the HTML. Exits non-zero if none is embedded. "
        "A URL is downloaded in full within 30 seconds and up to 16 MB; a slower or larger page fails.",
    )
    parser.add_argument(
        "--pdf",
        metavar="PATH",
        help="render straight to a PDF at PATH (drives a headless Chrome/Chromium/Edge, so needs one "
        "installed; set SKALDR_BROWSER to override discovery). Prints the full page's print styling.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="re-render to HTML on every save of the content file, a live edit-preview loop; Ctrl-C to "
        "stop. HTML only; can't combine with --check/--emit-json/--pdf. Watches the file, every file it "
        "!includes and, for an index, every part. Needs a process that stays alive: under an agent "
        "harness that reaps background jobs between turns, use --if-stale + --live instead.",
    )
    parser.add_argument(
        "--if-stale",
        action="store_true",
        help="render only when the output is missing, older than the content file, any file it "
        "!includes or any part of an index, or written with other --embed/--no-source/--live options; "
        "otherwise print 'up to date' and exit 0. Without --live it keeps the reloader of a page "
        "rendered with --live, so `--live` once and `--if-stale` after every edit keeps the page live. "
        "Makes an unconditional re-render after every edit free, so no watcher process is needed.",
    )
    parser.add_argument(
        "--live",
        nargs="?",
        const=0,
        type=int,
        metavar="MS",
        help="add a self-refreshing reloader to the page: it re-reads itself from disk when you return "
        "to the tab, so a re-render appears without a manual refresh. Scroll position and open sections "
        "survive. Pass milliseconds to also poll on a timer (for a screen that never loses focus). Full "
        "pages only: an --embed fragment is published as an Artifact and must not reload on a reader's "
        "screen.",
    )
    parser.add_argument(
        "--export",
        choices=EXPORT_TARGETS,
        help="write the document as Markdown instead of HTML: `notion` writes Notion-flavored Markdown "
        "for a Notion page; `markdown` writes GitHub-flavored Markdown for a README, a PR body or a wiki.",
    )
    parser.add_argument(
        "--export-dir",
        metavar="DIR",
        help="where --export writes (default: out/<data-stem>.<target>/)",
    )
    parser.add_argument(
        "--chunk",
        type=int,
        metavar="N",
        help="with --export notion: split the page into files of at most N characters, counted in Unicode "
        "code points rather than bytes, for a tool or a paste box that caps its input size. Whole sections "
        "go together where they fit; a longer section splits between its blocks, and a longer table into "
        "tables that repeat its header. A single block longer than N stays whole.",
    )
    parser.add_argument(
        "--write-schema",
        metavar="PATH",
        help="write the JSON Schema for content files to PATH and exit",
    )
    parser.add_argument(
        "--guide",
        nargs="?",
        const=True,
        metavar="NAME",
        help="print the authoring guide (blocks, rules, a complete example) and exit; give a block name "
        "(`--guide request`) to print just that block's row, its guide section and its fields, or a "
        'section title (`--guide "rich text"`) to print just that section',
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="with --guide: list the guide's sections and the block names, one per line",
    )
    parser.add_argument(
        "--install-skill",
        action="store_true",
        help="install skaldr's Claude skill into ~/.claude/skills (copies it; run once, survives "
        "upgrades), then exit",
    )
    parser.add_argument(
        "--install-plan-rule",
        action="store_true",
        help="add skaldr's live-plan-doc rule to ~/.claude/CLAUDE.md, which steers the agent to keep its "
        "working plans as live skaldr docs (delete the marked block to remove), then exit",
    )
    args = parser.parse_args(arguments)
    _return_a_swallowed_content_file(args)
    _refuse_company_for_a_standalone_mode(parser, args)
    _refuse_a_list_without_the_whole_guide(parser, args)

    # Opportunistically refresh already-installed skills that drifted after an upgrade. Fail-safe and
    # silent unless it writes; `--install-skill` below does its own (create-or-refresh) pass.
    if not args.install_skill:
        sync_installed_skills()

    if args.install_skill:
        return install_skill()

    if args.install_plan_rule:
        return install_plan_rule()

    if args.guide is not None:
        try:
            print(_guide_output(args.guide, args.list))
        except UnknownGuideTopicError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
        except OSError as err:
            print(f"error: could not read the bundled guide: {err}", file=sys.stderr)
            return 1
        return 0

    if args.write_schema:
        schema_path = Path(args.write_schema)
        try:
            replace_file(schema_path, json.dumps(Report.model_json_schema(), indent=2) + "\n")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"OK  {schema_path}")
        return 0

    if args.extract_source:
        return _extract_source(args.extract_source)

    if args.check and args.emit_json:
        parser.error("--check and --emit-json are mutually exclusive (each is a distinct validate-only mode)")
    if args.emit_json and (args.out or args.pdf or args.embed):
        parser.error("--emit-json only validates: it writes no HTML, so -o/--pdf/--embed do nothing")
    if args.watch and (args.check or args.emit_json or args.pdf):
        parser.error("--watch re-renders HTML on change; it can't combine with --check/--emit-json/--pdf")
    if args.watch and args.if_stale:
        parser.error("--watch re-renders on every save, so --if-stale has nothing to skip; drop one of them")
    if args.live is not None and (args.emit_json or args.embed):
        parser.error(
            "--live adds a self-refreshing reloader to a full HTML page; it can't combine with "
            "--emit-json (it writes no page) or --embed (an Artifact must not reload itself)"
        )
    if args.live is not None and args.pdf and not args.out:
        parser.error(
            "--live lives in the HTML, and --pdf alone writes none; add -o to also write the page, "
            "or drop --live"
        )
    if args.live is not None and args.live < 0:
        parser.error("--live takes a poll interval in milliseconds, which cannot be negative")
    if args.if_stale and args.emit_json:
        parser.error("--if-stale skips a render that would be redundant; --emit-json renders nothing")
    if args.strict and not args.check:
        parser.error("--strict only applies to --check (it gates unfilled placeholders during validation)")
    if args.embed and args.pdf and not args.out:
        parser.error(
            "--embed has no effect with --pdf alone (no HTML is written); add -o to also "
            "write the embed fragment, or drop --embed"
        )
    if args.check and len(args.data) > 1 and (args.out or args.pdf or args.embed or args.export):
        parser.error(
            "an output flag renders one file: pass a single content file, or drop -o/--pdf/--embed/--export "
            "to validate the whole set"
        )
    _reject_flags_that_do_not_fit_an_export(parser, args)
    if args.check and not (args.out or args.pdf or args.embed) and (args.live is not None or args.if_stale):
        parser.error(
            "--live and --if-stale shape a render; --check alone writes nothing, so add "
            "-o/--pdf/--embed or drop them"
        )
    if args.no_source and not _writes_an_html_page(args):
        parser.error(
            "--no-source shapes the HTML page, and this command writes none; "
            "add -o to write one, or drop --no-source"
        )

    if args.check:
        if not args.data:
            parser.error("--check needs at least one content file")
        failed = _check_files(args.data, strict=args.strict)
        if failed or not (args.out or args.pdf or args.embed or args.export):
            return failed

    if not args.data:
        parser.error("a content file is required (or use --write-schema)")
    if len(args.data) > 1:
        parser.error("only one content file can be processed at a time (use --check to validate several)")

    data_path = Path(args.data[0]).resolve()
    try:
        out_path = _resolve_out_path(data_path, args.out)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.watch:
        return _watch(data_path, out_path, embed=args.embed, no_source=args.no_source, live=args.live)

    live: int | None = args.live
    if args.if_stale:
        recorded = _recorded_render(out_path)
        if live is None and recorded is not None:
            live = recorded.live
        requested = RenderOptions(
            embed=args.embed, live=live, source=not args.no_source, version=skaldr_version()
        )
        if not _is_stale(data_path, out_path, requested, recorded, pdf=args.pdf):
            print(f"up to date  {out_path}")
            return 0

    if args.emit_json:
        try:
            report = load_report(data_path)
        except ReportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(report.model_dump(mode="json"), indent=2))
        return 0
    if args.export:
        return _export_document(data_path, args.export, args.export_dir, args.chunk)
    written: list[Path] = []
    try:
        report = load_report(data_path)
        # HTML first — it needs no browser, so a later PDF failure never costs the reader the HTML.
        # Write HTML when asked (-o), or by default when no --pdf was requested.
        if args.out or not args.pdf:
            source = None if args.no_source else data_path.read_text(encoding="utf-8")
            render_report(report, out_path, embed=args.embed, source=source, live=live)
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


def _recorded_render(out_path: Path) -> RecordedRender | None:
    try:
        return recorded_render(out_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def _newest_content_mtime(data_path: Path) -> float | None:
    try:
        mtimes = [_mtime(path) for path in content_files(data_path)]
    except ReportError:
        return None
    if any(mtime is None for mtime in mtimes):
        return None
    return max(mtime for mtime in mtimes if mtime is not None)


def _watched_files(data_path: Path, known: tuple[Path, ...]) -> tuple[Path, ...]:
    try:
        return content_files(data_path)
    except ReportError:
        return known or (data_path,)


def _mtimes(paths: Sequence[Path]) -> tuple[float | None, ...]:
    return tuple(_mtime(path) for path in paths)


def _is_stale(
    data_path: Path,
    out_path: Path,
    requested: RenderOptions,
    recorded: RecordedRender | None,
    *,
    pdf: str | None = None,
) -> bool:
    if pdf:
        return True
    out_mtime = _mtime(out_path)
    if out_mtime is None or recorded is None or recorded.options != requested:
        return True
    content_mtime = _newest_content_mtime(data_path)
    return content_mtime is None or content_mtime > out_mtime


def _render_once(
    data_path: Path, out_path: Path, *, embed: bool, no_source: bool = False, live: int | None = None
) -> int:
    """Render the content file to HTML once. Returns 0 on success, 1 on a load/render error (printed) —
    it never raises, so the --watch loop survives an invalid mid-edit save."""
    try:
        report = load_report(data_path)
        source = None if no_source else data_path.read_text(encoding="utf-8")
        render_report(report, out_path, embed=embed, source=source, live=live)
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


def _watch(
    data_path: Path,
    out_path: Path,
    *,
    embed: bool,
    no_source: bool = False,
    interval: float = _POLL_INTERVAL_SECONDS,
    live: int | None = None,
) -> int:
    """Re-render to HTML whenever the content file or a file it pulls in changes, until interrupted.
    Polls the mtimes (no third-party watcher); a failing render prints its error and the loop keeps going."""
    print(f"watching {data_path}: re-rendering to {out_path} on change (Ctrl-C to stop)")
    try:
        _render_once(data_path, out_path, embed=embed, no_source=no_source, live=live)
        watched = _watched_files(data_path, ())
        last = _mtimes(watched)
        while True:
            time.sleep(interval)
            current = _mtimes(watched)
            if None in current or current == last:
                continue
            changed = next(
                path for path, before, now in zip(watched, last, current, strict=True) if before != now
            )
            print(f"\n{changed} changed, re-rendering:")
            _render_once(data_path, out_path, embed=embed, no_source=no_source, live=live)
            resolved = _watched_files(data_path, watched)
            last = current if resolved == watched else _mtimes(resolved)
            watched = resolved
    except KeyboardInterrupt:
        print("\nstopped watching")
        return 0


def _fetch_page(url: str) -> bytes:
    deadline = time.monotonic() + _FETCH_TIMEOUT_SECONDS
    received = bytearray()
    with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_SECONDS) as response:
        while chunk := response.read(_FETCH_CHUNK_BYTES):
            received += chunk
            if len(received) > _FETCH_LIMIT_BYTES:
                raise PageFetchError(f"the page is larger than {_FETCH_LIMIT_BYTES // (1024 * 1024)} MB")
            if time.monotonic() > deadline:
                raise PageFetchError(
                    f"the page took longer than {_FETCH_TIMEOUT_SECONDS} seconds to download"
                )
    return bytes(received)


def _extract_source(target: str) -> int:
    """Print the YAML source embedded in a rendered skaldr page — `target` is a local file or an
    http(s) URL. Reads the page (never into the caller's context) and prints only the source, so an
    agent recovers it without parsing the HTML. Returns 1 if the page carries no embedded source."""
    try:
        if target.startswith(("http://", "https://")):
            html = _fetch_page(target).decode("utf-8")
        else:
            html = Path(target).read_text(encoding="utf-8")
    except (OSError, ValueError) as err:
        print(f"error: could not read {target}: {err}", file=sys.stderr)
        return 1
    source = extract_source(html)
    if source is None:
        print(f"error: no embedded skaldr source found in {target}", file=sys.stderr)
        return 1
    print(source, end="")
    return 0


def _reject_flags_that_do_not_fit_an_export(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    if not args.export:
        if args.export_dir is not None or args.chunk is not None:
            parser.error("--export-dir and --chunk only apply with --export")
        return
    if args.export_dir is not None and not args.export_dir.strip():
        parser.error("--export-dir needs a folder path")
    if args.out or args.pdf or args.embed or args.watch or args.emit_json:
        parser.error(
            "--export writes its own files; it can't combine with -o/--pdf/--embed/--watch/--emit-json"
        )
    if args.live is not None or args.if_stale or args.no_source:
        parser.error("--live, --if-stale and --no-source shape an HTML render; --export writes none")
    if args.chunk is None:
        return
    if args.export != "notion":
        parser.error("--chunk splits a Notion page into files; it only applies with --export notion")
    if args.chunk < 1:
        parser.error("--chunk takes a positive character count")


def _export_document(data_path: Path, target: ExportTarget, export_dir: str | None, chunk: int | None) -> int:
    out_dir = (
        Path(export_dir) if export_dir is not None else Path("out") / f"{data_path.stem}.{target}"
    ).resolve()
    try:
        report = load_report(data_path)
        match target:
            case "notion":
                result = export_notion(report, out_dir, chunk=chunk)
            case "markdown":
                result = export_markdown(report, out_dir)
            case _:
                assert_never(target)
    except (ReportError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result.unreadable_manifest:
        manifest = out_dir / EXPORT_MANIFEST
        print(
            f"warning: {manifest} could not be read; pages an earlier export wrote were left in place",
            file=sys.stderr,
        )
    for heading in result.oversized_sections:
        print(
            f"warning: section '{heading}' holds a part that cannot be split to fit --chunk {chunk} "
            "(one block, or a heading with the block after it); that part stays whole",
            file=sys.stderr,
        )
    for path in result.files:
        print(f"OK  {path}")
    return 0


def _check_files(paths: Sequence[str], *, strict: bool = False) -> int:
    """Validate each content file and print one line per file, returning 1 if any file is invalid — it
    drops straight into a pre-commit hook or CI over a glob. Validation includes a render pass (no HTML
    is written), so a render-time error like a dangling `#anchor` link surfaces as FAIL too, not only
    schema errors. With `strict`, an unfilled `{{placeholder}}` also fails a file (else a noted-OK count)."""
    failed = 0
    for raw_path in paths:
        path = Path(raw_path)
        try:
            report = load_report(path)
            # Render (discarding output) to collect placeholders AND surface render-time errors (e.g. a
            # dangling anchor) as a clean FAIL — must stay inside the try so nothing escapes as a traceback.
            unfilled = find_placeholders(report)
        except ReportError as exc:
            failed += 1
            print(f"FAIL  {path}: {exc}", file=sys.stderr)
            continue
        if unfilled and strict:
            failed += 1
            print(
                f"FAIL  {path}: {_plural(len(unfilled), 'unfilled placeholder')}: {', '.join(unfilled)}",
                file=sys.stderr,
            )
        elif unfilled:
            print(f"OK    {path}  ({_plural(len(unfilled), 'unfilled placeholder')}: {', '.join(unfilled)})")
        else:
            print(f"OK    {path}")
    if failed:
        print(f"\n{_plural(failed, 'file')} failed", file=sys.stderr)
    return 1 if failed else 0


def _guide_source() -> str:
    return package_text("skill/GUIDE.md")


def _guide_output(topic: str | Literal[True], list_topics_only: bool) -> str:
    if list_topics_only:
        return list_topics(_guide_source())
    if topic is True:
        return _guide_text()
    return lookup(topic, _guide_source())


def _guide_text() -> str:
    """The authoring guide (GUIDE.md) with the live, tested example appended — printed by --guide."""
    guide = package_text("skill/GUIDE.md").rstrip()
    example = package_text("skill/example.yaml").rstrip()
    return f"{guide}\n\n## A complete example\n\n```yaml\n{example}\n```"


# Bundled skills, as (package resource dir, installed skill name under ~/.claude/skills/). The primary
# authoring skill plus task-specific add-ons; add a row (and a `skills/<name>/SKILL.md`) to ship more.
# The installed folder name matches each SKILL.md's `name:` frontmatter, as Claude Code requires.
_BUNDLED_SKILLS: list[tuple[str, str]] = [
    ("skill", "skaldr"),
    ("skills/skaldr-presentation", "skaldr-presentation"),
    ("skills/skaldr-reflect", "skaldr-reflect"),
]


def _skill_up_to_date(src: Path, dest_file: Path) -> bool:
    """True when the installed SKILL.md exists and is byte-identical to the bundled source — the guard
    that makes both `--install-skill` and the on-invoke sync a clean no-op when nothing changed."""
    return dest_file.is_file() and dest_file.read_bytes() == src.read_bytes()


def _copy_skill(src: Path, dest_file: Path) -> None:
    replace_file(dest_file, src.read_text(encoding="utf-8"))


def install_skill(home: Path | None = None) -> int:
    """Copy every bundled skill's SKILL.md into its own <home>/.claude/skills/<name>/ (see
    `_BUNDLED_SKILLS`). Copies of stable files — not links into the versioned install — so it runs
    ONCE and survives upgrades; version-specific detail is fetched at author time via `skaldr --guide`
    / `--write-schema`. Update-only (a byte-identical skill is left untouched, so re-running is a clean
    no-op); migrates an older symlinked install; advises if ~/.claude is absent. The live-plan-doc
    CLAUDE.md rule is a separate opt-in — see `install_plan_rule`."""
    if home is None:
        home = Path.home()
    sources = [(package_path(src_dir) / "SKILL.md", name) for src_dir, name in _BUNDLED_SKILLS]
    missing = [name for src, name in sources if not src.is_file()]
    if missing:
        print(f"error: bundled skill(s) not found in this install: {', '.join(missing)}", file=sys.stderr)
        return 1

    claude_dir = home / ".claude"
    skills_dir = claude_dir / "skills"
    if not claude_dir.exists():
        print("Claude Code doesn't appear to be set up (~/.claude is missing).")
        print("If you use Claude Code, copy the skills in yourself:")
        for src, name in sources:
            print(f"    mkdir -p {skills_dir / name} && cp {src} {skills_dir / name}/")
        return 0

    for src, name in sources:
        dest_dir = skills_dir / name
        dest_file = dest_dir / "SKILL.md"
        try:
            if dest_dir.is_symlink():
                print(f"note: migrating an older symlinked install at {dest_dir}")
                dest_dir.unlink()  # older skaldr symlinked this dir into the versioned install
            dest_dir.mkdir(parents=True, exist_ok=True)
            if dest_file.is_symlink():
                # a live-edit link into a checkout — writing through it would clobber the tracked source
                print(f"note: leaving the symlinked skill file at {dest_file} as-is")
                continue
            if _skill_up_to_date(src, dest_file):
                print(f"OK  {name} skill already up to date -> {dest_file}")
                continue
            _copy_skill(src, dest_file)
        except OSError as err:
            print(f"error: could not install the skill into {dest_dir}: {err}", file=sys.stderr)
            return 1
        print(f"OK  installed {name} skill -> {dest_file}")
    print("    Restart Claude Code (or reload skills) to pick them up.")
    print("    (run `skaldr --install-plan-rule` to also have the agent keep its working plans as")
    print("     live skaldr docs)")
    return 0


def sync_installed_skills(home: Path | None = None) -> None:
    """Opportunistic refresh, run at the top of every `skaldr` invocation: for each bundled skill that is
    ALREADY installed under ~/.claude/skills, rewrite its SKILL.md if it has drifted from the packaged
    copy — so after `brew upgrade skaldr` the skill refreshes itself on the next run, no manual
    `--install-skill`, and without the Homebrew formula ever writing into $HOME.

    Deliberately conservative, because a plain `skaldr report.yaml` must never surprise:
    - never CREATES a skill (an absent one stays absent — installing is a deliberate `--install-skill`);
    - never touches a SYMLINKED install or SKILL.md (a contributor's live-edit link into the repo —
      overwriting it would clobber the tracked source);
    - update-only (byte-identical → no write, no mtime churn) and silent unless it actually refreshes;
    - never raises (a read-only/odd ~/.claude must not break a render), and short-circuits at once when
      ~/.claude/skills doesn't exist.

    Set `SKALDR_SKILL_SYNC=0` to disable it (contributors doing live edits, CI)."""
    if os.environ.get("SKALDR_SKILL_SYNC") == "0":
        return
    try:
        # `Path.home()` raises RuntimeError when $HOME is unresolvable (a minimal container with no
        # passwd entry); `is_dir()` raises PermissionError on an unsearchable ~/.claude. Neither may
        # crash a render, so the whole setup is guarded before the per-skill loop takes over.
        if home is None:
            home = Path.home()
        skills_dir = home / ".claude" / "skills"
        if not skills_dir.is_dir():
            return
    except (OSError, RuntimeError):
        return
    for src_dir, name in _BUNDLED_SKILLS:
        dest_dir = skills_dir / name
        dest_file = dest_dir / "SKILL.md"
        try:
            # refresh only an existing, non-symlinked install; skip (never create, never clobber) the
            # rest. `or` short-circuits, so dest_file.is_symlink() is reached only for a real dir.
            if dest_dir.is_symlink() or not dest_dir.is_dir() or dest_file.is_symlink():
                continue
            src = package_path(src_dir) / "SKILL.md"
            if not src.is_file() or _skill_up_to_date(src, dest_file):
                continue
            _copy_skill(src, dest_file)
            print(
                f"skaldr: refreshed the '{name}' skill in {dest_dir} (a newer copy shipped)", file=sys.stderr
            )
        except OSError:
            continue  # one skill's FS error must skip only that skill — never the rest, never the render


def install_plan_rule(home: Path | None = None) -> int:
    """Add or refresh skaldr's live-plan-doc rule in <home>/.claude/CLAUDE.md (see `_install_plan_rule`).
    A separate opt-in from `install_skill`, so installing the skill never silently edits CLAUDE.md.
    Advises if ~/.claude is absent."""
    if home is None:
        home = Path.home()
    claude_dir = home / ".claude"
    md_path = claude_dir / "CLAUDE.md"
    if not claude_dir.exists():
        print("Claude Code doesn't appear to be set up (~/.claude is missing).")
        print(f"If you use Claude Code, add the rule to {md_path} once it exists.")
        return 0

    try:
        action = _install_plan_rule(claude_dir)
    except OSError as err:
        print(f"error: could not update {md_path}: {err}", file=sys.stderr)
        return 1
    print(f"OK  {action} the plan-workflow rule in {md_path}")
    print("    (the skaldr:plan-rule block; delete it to opt out)")
    print("    Restart Claude Code to pick it up.")
    return 0


def _install_plan_rule(claude_dir: Path) -> Literal["added", "updated"]:
    """Add or refresh the skaldr plan-workflow rule in <claude_dir>/CLAUDE.md as a marker-delimited
    block. Strips every complete existing block and re-appends one fresh, so a re-install never
    duplicates and only ever touches its own block — all other content is preserved (a stray, unpaired
    marker is left untouched, never built on). Raises OSError on a read/write failure."""
    rule = package_text("skill/plan-rule.md").rstrip()
    block = f"{_PLAN_RULE_BEGIN}\n{rule}\n{_PLAN_RULE_END}\n"
    md_path = claude_dir / "CLAUDE.md"
    existing = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    had_block = bool(_PLAN_RULE_BLOCK.search(existing))
    kept = _PLAN_RULE_BLOCK.sub("", existing).rstrip()
    replace_file(md_path, f"{kept}\n\n{block}" if kept else block)
    return "updated" if had_block else "added"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


if __name__ == "__main__":
    sys.exit(main())
