import argparse
import sys
import webbrowser
from collections.abc import Callable
from getpass import getpass
from typing import NamedTuple, get_args

import httpx2

from skaldr.auth import printable_only
from skaldr.auth.jira import API_TOKENS_PAGE, verify_jira_token
from skaldr.auth.notion import (
    DEFAULT_CALLBACK_PORT,
    INTEGRATIONS_PAGE,
    redirect_uri_for,
    revoke_notion_token,
    save_notion_replacing_the_old_sign_in,
    sign_in_to_notion,
)
from skaldr.auth.store import (
    JiraCredentials,
    NotionCredentials,
    StoredEntry,
    find_jira,
    find_notion,
    forget,
    jira_from_environment,
    normalise_site,
    notion_client_from_environment,
    notion_from_environment,
    refuse_an_unusable_keychain,
    save_jira,
    stored_jira_sign_ins,
    stored_notion_sign_ins,
)
from skaldr.errors import AuthError
from skaldr.services import Service

_UNNAMED_WORKSPACE = "(unnamed workspace)"


class _StatusLine(NamedTuple):
    text: str
    failed: bool = False


def main(
    argv: list[str],
    *,
    transport: httpx2.BaseTransport | None = None,
    open_browser: Callable[[str], object] = webbrowser.open,
) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "notion":
            _sign_in_to_notion(args.port, transport, open_browser)
        elif args.command == "jira":
            _sign_in_to_jira(transport)
        elif args.command == "status":
            return _print_status()
        elif args.command == "logout" and args.service == "notion":
            _log_out_of_notion(args.selector, transport)
        elif args.command == "logout" and args.service == "jira":
            _log_out_of_jira(args.selector)
        else:
            raise AssertionError(f"skaldr auth has no handler for {args.command!r}")
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nerror: cancelled", file=sys.stderr)
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skaldr auth",
        description="Sign skaldr in to Notion and Jira. Credentials go to the system keychain; the "
        "NOTION_* and JIRA_* environment variables override it.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    notion = commands.add_parser("notion", help="sign in to Notion through your own OAuth public connection")
    notion.add_argument(
        "--port",
        type=_tcp_port,
        default=DEFAULT_CALLBACK_PORT,
        help=f"the port in the redirect URI you registered with Notion (default {DEFAULT_CALLBACK_PORT})",
    )
    commands.add_parser("jira", help="sign in to Jira Cloud with your account email and an API token")
    commands.add_parser("status", help="list every sign-in, who it is as, and where the credentials live")
    logout = commands.add_parser(
        "logout", help="remove one sign-in from the keychain, revoking the Notion token first"
    )
    logout.add_argument("service", choices=get_args(Service))
    logout.add_argument(
        "selector",
        nargs="?",
        help="the Jira site, or the Notion workspace id or name; needed only when several are signed in",
    )
    return parser


def _tcp_port(text: str) -> int:
    refusal = f"{text!r} is not a TCP port (1 to 65535)"
    try:
        port = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(refusal) from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(refusal)
    return port


def _sign_in_to_notion(
    port: int, transport: httpx2.BaseTransport | None, open_browser: Callable[[str], object]
) -> None:
    refuse_an_unusable_keychain()
    print(
        f"Register a public Notion connection once at {INTEGRATIONS_PAGE}, with redirect URI "
        f"{redirect_uri_for(port)}"
    )
    from_environment_id, from_environment_secret = notion_client_from_environment()
    client_id = _ascii(
        from_environment_id
        or _required(input("Notion OAuth client ID: "), "A Notion OAuth client ID is required"),
        "client ID",
    )
    client_secret = _ascii(
        from_environment_secret
        or _required(getpass("Notion OAuth client secret: "), "A Notion OAuth client secret is required"),
        "client secret",
    )

    def announce_then_open(url: str) -> None:
        print(f"Opening Notion in your browser. If it does not open, visit:\n  {url}", flush=True)
        open_browser(url)

    credentials = sign_in_to_notion(
        client_id, client_secret, open_browser=announce_then_open, port=port, transport=transport
    )
    warnings = save_notion_replacing_the_old_sign_in(credentials, transport=transport)
    workspace = _workspace_name(credentials) or _UNNAMED_WORKSPACE
    print(f"Signed in to Notion workspace {workspace}. Saved to the keychain.")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)


def _sign_in_to_jira(transport: httpx2.BaseTransport | None) -> None:
    refuse_an_unusable_keychain()
    site = normalise_site(input("Jira site (https://<site>.atlassian.net): "))
    email = _required(input("Atlassian account email: "), "An Atlassian account email is required")
    api_token = _required(getpass(f"API token (from {API_TOKENS_PAGE}): "), "An API token is required")
    credentials = verify_jira_token(site, email, api_token, transport=transport)
    save_jira(credentials)
    display_name = _display_name(credentials)
    signed_in = (
        f"Signed in to Jira at {site}"
        if display_name is None
        else f"Signed in to Jira at {site} as {display_name}"
    )
    print(f"{signed_in}. Saved to the keychain.")


def _print_status() -> int:
    sections = (("notion", _notion_status_lines), ("jira", _jira_status_lines))
    exit_code = 0
    for service, describe in sections:
        try:
            lines = describe()
        except AuthError as exc:
            lines = [_StatusLine(f"error: {exc}", failed=True)]
        for line in lines:
            exit_code = exit_code or int(line.failed)
            print(f"{service:<8}{line.text}")
    return exit_code


def _log_out_of_notion(workspace: str | None, transport: httpx2.BaseTransport | None) -> None:
    entry = find_notion(workspace)
    if entry is None:
        where = "" if workspace is None else f" workspace {printable_only(workspace)}"
        print(f"Not signed in to Notion{where}.")
        return
    revoked = _notion_token_was_revoked(entry, transport)
    if not forget(entry):
        outcome = "The Notion token was revoked" if revoked else "The Notion token was not revoked"
        print(f"{outcome}, but a newer sign-in was stored in the meantime and was kept.")
        return
    outcome = "token revoked and removed from the keychain" if revoked else "removed from the keychain"
    print(f"Signed out of Notion: {outcome}.")


def _notion_token_was_revoked(
    entry: StoredEntry[NotionCredentials], transport: httpx2.BaseTransport | None
) -> bool:
    if entry.credentials is None:
        print("warning: the stored Notion entry is unreadable, so its token was not revoked", file=sys.stderr)
        return False
    try:
        revoke_notion_token(entry.credentials, transport=transport)
    except AuthError as exc:
        print(f"warning: {exc}", file=sys.stderr)
        return False
    return True


def _log_out_of_jira(site: str | None) -> None:
    entry = find_jira(site)
    if entry is None:
        where = "" if site is None else f" at {normalise_site(site)}"
        print(f"Not signed in to Jira{where}.")
        return
    if not forget(entry):
        print("A newer Jira sign-in was stored in the meantime and was kept.")
        return
    print(f"Signed out of Jira: removed from the keychain. Revoke the API token itself at {API_TOKENS_PAGE}")


def _status_lines(
    environment: Callable[[], str | None],
    stored: Callable[[], list[_StatusLine]],
    signed_out: str,
) -> list[_StatusLine]:
    lines: list[_StatusLine] = []
    from_environment: str | None = None
    try:
        from_environment = environment()
    except AuthError as exc:
        lines.append(_StatusLine(f"error: {exc}", failed=True))
    if from_environment is not None:
        lines.append(_StatusLine(from_environment))
    try:
        lines.extend(stored())
    except AuthError as exc:
        keychain_line = (
            _StatusLine(f"error: {exc}", failed=True)
            if from_environment is None
            else _StatusLine(f"stored sign-ins not read: {exc}")
        )
        lines.append(keychain_line)
    return lines or [_StatusLine(signed_out)]


def _notion_status_lines() -> list[_StatusLine]:
    def environment() -> str | None:
        if notion_from_environment() is None:
            return None
        return "access token from NOTION_ACCESS_TOKEN (environment)"

    return _status_lines(
        environment,
        lambda: [_describe_stored_notion(entry) for entry in stored_notion_sign_ins()],
        "not signed in (run `skaldr auth notion`)",
    )


def _jira_status_lines() -> list[_StatusLine]:
    def environment() -> str | None:
        from_environment = jira_from_environment()
        if from_environment is None:
            return None
        return f"JIRA_EMAIL, JIRA_API_TOKEN for {from_environment.site} (environment)"

    return _status_lines(
        environment,
        lambda: [_describe_stored_jira(entry) for entry in stored_jira_sign_ins()],
        "not signed in (run `skaldr auth jira`)",
    )


def _describe_stored_notion(entry: StoredEntry[NotionCredentials]) -> _StatusLine:
    if entry.credentials is None:
        return _StatusLine(f"error: {entry.unreadable_message}", failed=True)
    workspace = _workspace_name(entry.credentials) or _UNNAMED_WORKSPACE
    if entry.credentials.workspace_id is None:
        identified = f" (no workspace id; name it as {entry.identifier})"
    else:
        identified = f" (id {entry.credentials.workspace_id})"
    return _StatusLine(f"signed in to workspace {workspace}{identified} (keychain)")


def _describe_stored_jira(entry: StoredEntry[JiraCredentials]) -> _StatusLine:
    if entry.credentials is None:
        return _StatusLine(f"error: {entry.unreadable_message}", failed=True)
    display_name = _display_name(entry.credentials)
    if display_name is None:
        return _StatusLine(f"signed in to {entry.credentials.site} (keychain)")
    return _StatusLine(f"signed in to {entry.credentials.site} as {display_name} (keychain)")


def _workspace_name(credentials: NotionCredentials) -> str | None:
    return printable_only(credentials.workspace_name or "") or None


def _display_name(credentials: JiraCredentials) -> str | None:
    return printable_only(credentials.display_name or "") or None


def _required(answer: str, refusal: str) -> str:
    stripped = answer.strip()
    if not stripped:
        raise AuthError(refusal)
    return stripped


def _ascii(value: str, name: str) -> str:
    if not value.isascii():
        raise AuthError(f"The Notion OAuth {name} has characters outside ASCII; copy it from Notion again")
    return value
