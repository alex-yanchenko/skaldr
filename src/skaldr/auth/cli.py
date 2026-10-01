import argparse
import sys
import webbrowser
from collections.abc import Callable
from getpass import getpass
from typing import get_args

import httpx2

from skaldr.auth.jira import API_TOKENS_PAGE, verify_jira_token
from skaldr.auth.notion import (
    DEFAULT_CALLBACK_PORT,
    INTEGRATIONS_PAGE,
    redirect_uri_for,
    revoke_notion_token,
    sign_in_to_notion,
)
from skaldr.auth.store import (
    JiraCredentials,
    NotionCredentials,
    Service,
    SignIn,
    forget,
    load_jira,
    load_notion,
    normalise_site,
    notion_client_from_environment,
    save_jira,
    save_notion,
    stored_notion,
)
from skaldr.errors import AuthError


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
            _log_out_of_notion(transport)
        elif args.command == "logout":
            _log_out_of_jira()
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nerror: sign-in cancelled", file=sys.stderr)
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
    commands.add_parser(
        "status", help="show who each service is signed in as, and where the credentials live"
    )
    logout = commands.add_parser(
        "logout", help="remove a service's credentials from the keychain, revoking the Notion token first"
    )
    logout.add_argument("service", choices=get_args(Service))
    return parser


def _tcp_port(text: str) -> int:
    try:
        port = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{text!r} is not a TCP port (1 to 65535)") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"{text!r} is not a TCP port (1 to 65535)")
    return port


def _sign_in_to_notion(
    port: int, transport: httpx2.BaseTransport | None, open_browser: Callable[[str], object]
) -> None:
    print(
        f"Register a public Notion connection once at {INTEGRATIONS_PAGE}, with redirect URI "
        f"{redirect_uri_for(port)}"
    )
    client_id, client_secret = notion_client_from_environment()
    client_id = client_id or _required(
        input("Notion OAuth client ID: "), "A Notion OAuth client ID is required"
    )
    client_secret = client_secret or _required(
        getpass("Notion OAuth client secret: "), "A Notion OAuth client secret is required"
    )

    def announce_then_open(url: str) -> None:
        print(f"Opening Notion in your browser. If it does not open, visit:\n  {url}", flush=True)
        open_browser(url)

    credentials = sign_in_to_notion(
        client_id, client_secret, open_browser=announce_then_open, port=port, transport=transport
    )
    save_notion(credentials)
    print(f"Signed in to Notion workspace {_workspace(credentials)}. Saved to the keychain.")


def _sign_in_to_jira(transport: httpx2.BaseTransport | None) -> None:
    site = normalise_site(input("Jira site (https://<site>.atlassian.net): "))
    email = _required(input("Atlassian account email: "), "An Atlassian account email is required")
    api_token = _required(getpass(f"API token (from {API_TOKENS_PAGE}): "), "An API token is required")
    credentials = verify_jira_token(site, email, api_token, transport=transport)
    save_jira(credentials)
    print(f"Signed in to Jira at {site} as {credentials.display_name}. Saved to the keychain.")


def _print_status() -> int:
    notion_line, notion_failed = _status_line(lambda: _describe_notion(load_notion()))
    jira_line, jira_failed = _status_line(lambda: _describe_jira(load_jira()))
    print(f"notion  {notion_line}")
    print(f"jira    {jira_line}")
    return 1 if notion_failed or jira_failed else 0


def _status_line(describe: Callable[[], str]) -> tuple[str, bool]:
    try:
        return describe(), False
    except AuthError as exc:
        return f"error: {exc}", True


def _log_out_of_notion(transport: httpx2.BaseTransport | None) -> None:
    revoked = _revoke_the_stored_notion_token(transport)
    if not forget("notion"):
        print("Not signed in to Notion.")
        return
    outcome = "token revoked and removed from the keychain" if revoked else "removed from the keychain"
    print(f"Signed out of Notion: {outcome}.")


def _revoke_the_stored_notion_token(transport: httpx2.BaseTransport | None) -> bool:
    try:
        stored = stored_notion()
        if stored is None:
            return False
        revoke_notion_token(stored, transport=transport)
    except AuthError as exc:
        print(f"warning: {exc}", file=sys.stderr)
        return False
    return True


def _log_out_of_jira() -> None:
    if not forget("jira"):
        print("Not signed in to Jira.")
        return
    print(f"Signed out of Jira: removed from the keychain. Revoke the API token itself at {API_TOKENS_PAGE}")


def _describe_notion(sign_in: SignIn[NotionCredentials] | None) -> str:
    if sign_in is None:
        return "not signed in (run `skaldr auth notion`)"
    if sign_in.source == "environment":
        return "access token from NOTION_ACCESS_TOKEN (environment)"
    return f"signed in to workspace {_workspace(sign_in.credentials)} (keychain)"


def _describe_jira(sign_in: SignIn[JiraCredentials] | None) -> str:
    if sign_in is None:
        return "not signed in (run `skaldr auth jira`)"
    credentials = sign_in.credentials
    if sign_in.source == "environment":
        return f"{credentials.email} at {credentials.site} (environment)"
    return f"signed in to {credentials.site} as {credentials.display_name} (keychain)"


def _workspace(credentials: NotionCredentials) -> str:
    return credentials.workspace_name or "(unnamed workspace)"


def _required(answer: str, refusal: str) -> str:
    stripped = answer.strip()
    if not stripped:
        raise AuthError(refusal)
    return stripped
