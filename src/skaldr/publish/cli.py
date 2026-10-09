import argparse
import sys
from pathlib import Path

from skaldr.errors import ConnectorError, PublishError, ReportError
from skaldr.publish.connector import ConnectorRegistry
from skaldr.publish.engine import (
    Applied,
    Prepared,
    apply_publish,
    diff_publish,
    dry_run_publish,
    prepare_publish,
    publish_status,
    refusal_message,
)
from skaldr.publish.jira import JiraConnector
from skaldr.publish.output import diff_json, diff_lines, remote_edit_lines, status_line
from skaldr.publish.plan import describe_plan

NOTHING_PUBLISHED = (
    "Nothing to publish: the `publish` block has no targets and no item of this document is published."
)


def installed_connectors() -> ConnectorRegistry:
    return ConnectorRegistry((JiraConnector(),))


def _parsers() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    parser = argparse.ArgumentParser(
        prog="skaldr",
        description="Publish a skaldr document to the Notion pages and Jira issues its `publish` block "
        "names.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser(
        "publish",
        help="print what publishing would do; with --apply, do it",
        description="Plan or apply a publish.",
    )
    publish.add_argument("document", type=Path, help="the content YAML with a `publish` block")
    publish.add_argument("--apply", action="store_true", help="send the plan to the services")
    publish.add_argument(
        "--overwrite",
        action="store_true",
        help="with --apply: replace the remote edits the last diff showed with the YAML's content",
    )
    diff = commands.add_parser(
        "diff", help="show remote edits since the last publish and what the YAML would change"
    )
    diff.add_argument("document", type=Path, help="the content YAML with a `publish` block")
    diff.add_argument("--json", action="store_true", help="print the same facts as JSON")
    status = commands.add_parser(
        "status", help="name each item as in sync, edited remotely, changed, removed or never published"
    )
    status.add_argument("document", type=Path, help="the content YAML with a `publish` block")
    return parser, publish


def _print_step(target: str, described: str) -> None:
    print(f"{target}: {described}", flush=True)


def _has_no_target_and_no_published_item(prepared: Prepared) -> bool:
    return not prepared.plan.targets


def _dry_run(prepared: Prepared, document: Path) -> int:
    dry_run = dry_run_publish(prepared)
    if _has_no_target_and_no_published_item(prepared) and dry_run.refusal is None:
        print(NOTHING_PUBLISHED)
        return 0
    print("\n".join(describe_plan(dry_run.plan)))
    if dry_run.edits:
        print("\n".join(remote_edit_lines(dry_run.edits)))
    if dry_run.refusal is not None:
        verb = "stop" if dry_run.edits else "refuse"
        print(f"error: --apply would {verb}: {dry_run.refusal}", file=sys.stderr)
        return 1
    print(f"Dry run: nothing was sent. Publish with `skaldr publish {document} --apply`.")
    return 0


def _publish(prepared: Prepared, document: Path, *, apply: bool, overwrite: bool) -> int:
    if not apply:
        return _dry_run(prepared, document)
    outcome = apply_publish(prepared, overwrite=overwrite, on_step=_print_step)
    if isinstance(outcome, Applied):
        if not outcome.steps and _has_no_target_and_no_published_item(prepared):
            print(NOTHING_PUBLISHED)
            return 0
        if not outcome.steps:
            print("Nothing to publish: every item matches the YAML.")
            return 0
        steps = "1 step" if len(outcome.steps) == 1 else f"{len(outcome.steps)} steps"
        print(f"Published {steps}. The publish state is in {prepared.state_path}.")
        return 0
    print("\n".join(remote_edit_lines(outcome.edits)))
    print(f"error: {refusal_message(outcome)}", file=sys.stderr)
    return 1


def _run(args: argparse.Namespace, registry: ConnectorRegistry) -> int:
    prepared = prepare_publish(args.document, registry)
    if args.command == "publish":
        return _publish(prepared, args.document, apply=args.apply, overwrite=args.overwrite)
    if args.command == "diff":
        diff = diff_publish(prepared)
        print(diff_json(diff) if args.json else "\n".join(diff_lines(diff)))
        return 0
    if args.command == "status":
        for status in publish_status(prepared):
            print(status_line(status))
        return 0
    raise AssertionError(f"skaldr has no publish handler for {args.command!r}")


def main(argv: list[str], *, registry: ConnectorRegistry | None = None) -> int:
    parser, publish_parser = _parsers()
    args = parser.parse_args(argv)
    if args.command == "publish" and args.overwrite and not args.apply:
        publish_parser.error("--overwrite replaces remote edits while publishing, so it needs --apply")
    try:
        return _run(args, registry if registry is not None else installed_connectors())
    except (ReportError, PublishError, ConnectorError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
