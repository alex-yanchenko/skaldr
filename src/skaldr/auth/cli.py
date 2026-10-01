import argparse
import os
import sys
import webbrowser
from collections.abc import Callable
from getpass import getpass

import httpx2

from skaldr.auth.jira import API_TOKENS_PAGE, normalise_site, verify_jira_token
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
    SignIn,
    forget,
    load_jira,
    load_notion,
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
            print(f"notion  {_describe_notion(load_notion())}")
            print(f"jira    {_describe_jira(load_jira())}")
        elif args.service == "notion":
            _log_out_of_notion(transport)
        else:
            _log_out_of_jira()
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
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
        type=int,
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
    logout.add_argument("service", choices=["notion", "jira"])
    return parser


def _sign_in_to_notion(
    port: int, transport: httpx2.BaseTransport | None, open_browser: Callable[[str], object]
) -> None:
    print(
        f"Register a public Notion connection once at {INTEGRATIONS_PAGE}, with redirect URI "
        f"{redirect_uri_for(port)}"
    )
    client_id = os.environ.get("NOTION_CLIENT_ID") or _required(
        input("Notion OAuth client ID: "), "A Notion OAuth client ID is required"
    )
    client_secret = os.environ.get("NOTION_CLIENT_SECRET") or _required(
        getpass("Notion OAuth client secret: "), "A Notion OAuth client secret is required"
    )

    def announce_then_open(url: str) -> None:
        print(f"Opening Notion in your browser. If it does not open, visit:\n  {url}", flush=True)
        open_browser(url)

    credentials = sign_in_to_notion(
        client_id, client_secret, open_browser=announce_then_open, port=port, transport=transport
    )
    save_notion(credentials)
    print(f"Signed in to Notion workspace {credentials.workspace_name}. Saved to the keychain.")


def _sign_in_to_jira(transport: httpx2.BaseTransport | None) -> None:
    site = normalise_site(input("Jira site (https://<site>.atlassian.net): "))
    email = _required(input("Atlassian account email: "), "An Atlassian account email is required")
    api_token = _required(getpass(f"API token (from {API_TOKENS_PAGE}): "), "An API token is required")
    credentials = verify_jira_token(site, email, api_token, transport=transport)
    save_jira(credentials)
    print(f"Signed in to Jira at {site} as {credentials.display_name}. Saved to the keychain.")


def _log_out_of_notion(transport: httpx2.BaseTransport | None) -> None:
    stored = stored_notion()
    if stored is None:
        print("Not signed in to Notion.")
        return
    try:
        revoke_notion_token(stored, transport=transport)
    except AuthError as exc:
        print(f"warning: {exc}", file=sys.stderr)
        forget("notion")
        print("Signed out of Notion: removed from the keychain.")
        return
    forget("notion")
    print("Signed out of Notion: token revoked and removed from the keychain.")


def _log_out_of_jira() -> None:
    if forget("jira"):
        print(
            f"Signed out of Jira: removed from the keychain. Revoke the API token itself at {API_TOKENS_PAGE}"
        )
    else:
        print("Not signed in to Jira.")


def _describe_notion(sign_in: SignIn[NotionCredentials] | None) -> str:
    if sign_in is None:
        return "not signed in (run `skaldr auth notion`)"
    if sign_in.source == "environment":
        return "access token from NOTION_ACCESS_TOKEN (environment)"
    return f"signed in to workspace {sign_in.credentials.workspace_name} (keychain)"


def _describe_jira(sign_in: SignIn[JiraCredentials] | None) -> str:
    if sign_in is None:
        return "not signed in (run `skaldr auth jira`)"
    credentials = sign_in.credentials
    if sign_in.source == "environment":
        return f"{credentials.email} at {credentials.site} (environment)"
    return f"signed in to {credentials.site} as {credentials.display_name} (keychain)"


def _required(answer: str, refusal: str) -> str:
    if not answer.strip():
        raise AuthError(refusal)
    return answer.strip()
