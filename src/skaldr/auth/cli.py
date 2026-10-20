import argparse
import sys
import webbrowser
from collections.abc import Callable, Mapping
from getpass import getpass
from typing import NamedTuple, get_args
from uuid import UUID

import httpx2

from skaldr.auth import printable_only
from skaldr.auth.jira import API_TOKENS_PAGE, verify_jira_token
from skaldr.auth.notion import (
    DEFAULT_CALLBACK_PORT,
    INTEGRATIONS_PAGE,
    NotionSession,
    redirect_uri_for,
    revoke_notion_token,
    save_notion_replacing_the_old_sign_in,
    sign_in_to_notion,
)
from skaldr.auth.slack import SLACK_APPS_PAGE, SLACK_USER_SCOPES, verify_slack_token
from skaldr.auth.store import (
    SLACK_USER_TOKEN_PREFIX,
    SLACK_USER_TOKEN_VARIABLE,
    JiraCredentials,
    NotionCredentials,
    SignIn,
    SlackCredentials,
    StoredEntry,
    find_jira,
    find_notion,
    find_slack,
    forget,
    jira_from_environment,
    normalise_site,
    notion_client_from_environment,
    notion_from_environment,
    refuse_an_unusable_keychain,
    save_jira,
    save_slack,
    slack_from_environment,
    stored_jira_sign_ins,
    stored_notion_sign_ins,
    stored_slack_sign_ins,
)
from skaldr.auth.templates import (
    clear_notion_template,
    notion_templates,
    save_notion_template,
)
from skaldr.errors import AuthError, ConnectorError, SeveralSignInsError
from skaldr.publish.notion.api import NotionApi
from skaldr.publish.notion.template import check_the_template_is_empty
from skaldr.publish_block.notion import required_page_id
from skaldr.services import NotionService, Service

_UNNAMED_WORKSPACE = "(unnamed workspace)"
_TEMPLATE_EXPLANATION = (
    "A page template makes the pages skaldr creates keep the template page's Full width or Small text. "
    "It must be an empty page shared with your connection."
)
_TEMPLATE_PROMPT = "Notion page template link (Enter to skip): "
_FULL_WIDTH_NOTICE = (
    "Turn on Full width or Small text on the template page in Notion yourself: skaldr cannot set or read "
    "them, and pages created from the template keep them."
)
_SET_THE_TEMPLATE_LATER = "Set it later with `skaldr auth template notion <link>`."


class _StatusLine(NamedTuple):
    text: str
    failed: bool = False


class _TemplateHolder(NamedTuple):
    credentials: NotionCredentials
    workspace_id: UUID


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
        elif args.command == "slack":
            _sign_in_to_slack(transport)
        elif args.command == "status":
            return _print_status()
        elif args.command == "template":
            _manage_the_notion_template(args.link, args.clear, args.workspace, transport)
        elif args.command == "logout" and args.service == "notion":
            _log_out_of_notion(args.selector, transport)
        elif args.command == "logout" and args.service == "jira":
            _log_out_of_jira(args.selector)
        elif args.command == "logout" and args.service == "slack":
            _log_out_of_slack(args.selector)
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
        description="Sign skaldr in to Notion, Jira and Slack. Credentials go to the system keychain; the "
        "NOTION_*, JIRA_* and SLACK_USER_TOKEN environment variables override it.",
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
    commands.add_parser("slack", help="sign in to Slack with the user token of your own Slack app")
    commands.add_parser("status", help="list every sign-in, who it is as, and where the credentials live")
    template = commands.add_parser(
        "template",
        help="set, show or clear the empty Notion page whose page settings new pages are created from",
    )
    template.add_argument("service", choices=get_args(NotionService))
    one_action = template.add_mutually_exclusive_group()
    one_action.add_argument(
        "link", nargs="?", help="the Notion page URL or id to set as the template; left out, show it"
    )
    one_action.add_argument("--clear", action="store_true", help="remove the template")
    template.add_argument(
        "--workspace",
        help="the Notion workspace id or name; needed only when several are signed in",
    )
    logout = commands.add_parser(
        "logout", help="remove one sign-in from the keychain, revoking the Notion token first"
    )
    logout.add_argument("service", choices=get_args(Service))
    logout.add_argument(
        "selector",
        nargs="?",
        help="the Jira site, or the Notion or Slack workspace id or name; needed only when several are "
        "signed in",
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
    workspace = _workspace_named(credentials.workspace_name)
    print(f"Signed in to Notion workspace {workspace}. Saved to the keychain.")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    _offer_a_template(credentials, transport)


def _offer_a_template(credentials: NotionCredentials, transport: httpx2.BaseTransport | None) -> None:
    if not sys.stdin.isatty():
        return
    print(_TEMPLATE_EXPLANATION)
    try:
        answer = input(_TEMPLATE_PROMPT).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not answer:
        return
    try:
        _set_the_template(_template_holder(credentials), answer, transport)
    except AuthError as exc:
        print(f"warning: the page template was not set: {exc}. {_SET_THE_TEMPLATE_LATER}", file=sys.stderr)


def _manage_the_notion_template(
    link: str | None, clear: bool, workspace: str | None, transport: httpx2.BaseTransport | None
) -> None:
    if clear:
        _clear_the_template(_template_holder(_the_notion_sign_in(workspace)))
    elif link is not None:
        _set_the_template(_template_holder(_the_notion_sign_in(workspace)), link, transport)
    else:
        _show_the_templates(workspace)


def _find_the_notion_entry(workspace: str | None) -> StoredEntry[NotionCredentials] | None:
    try:
        return find_notion(workspace)
    except SeveralSignInsError as several:
        raise AuthError(f"{several} with --workspace") from None


def _the_notion_sign_in(workspace: str | None) -> NotionCredentials:
    entry = _find_the_notion_entry(workspace)
    if entry is None:
        where = "" if workspace is None else f" workspace {printable_only(workspace)}"
        raise AuthError(f"Not signed in to Notion{where}; run `skaldr auth notion`")
    if entry.credentials is None:
        raise AuthError(entry.unreadable_message)
    return entry.credentials


def _template_holder(credentials: NotionCredentials) -> _TemplateHolder:
    if credentials.workspace_id is None:
        raise AuthError(
            f"The Notion sign-in for workspace {_workspace_named(credentials.workspace_name)} has no "
            "workspace id, so it cannot hold a template; run `skaldr auth notion` again"
        )
    return _TemplateHolder(credentials, credentials.workspace_id)


def _set_the_template(holder: _TemplateHolder, link: str, transport: httpx2.BaseTransport | None) -> None:
    try:
        page_id = required_page_id(link)
    except ValueError as invalid:
        raise AuthError(str(invalid)) from None
    session = NotionSession(SignIn(holder.credentials, "keychain"), transport=transport)
    api = NotionApi(session, transport=transport)
    try:
        check_the_template_is_empty(api, page_id)
    except ConnectorError as refused:
        raise AuthError(str(refused)) from refused
    finally:
        api.close()
    save_notion_template(holder.workspace_id, page_id)
    workspace = _workspace_named(holder.credentials.workspace_name)
    print(f"Notion workspace {workspace}: new pages are created from template page {page_id}.")
    print(_FULL_WIDTH_NOTICE)


def _clear_the_template(holder: _TemplateHolder) -> None:
    workspace = _workspace_named(holder.credentials.workspace_name)
    if clear_notion_template(holder.workspace_id):
        print(f"Cleared the page template of Notion workspace {workspace}.")
    else:
        print(f"Notion workspace {workspace} has no page template.")


def _entries_to_show(workspace: str | None) -> list[StoredEntry[NotionCredentials]]:
    if workspace is None:
        return stored_notion_sign_ins()
    entry = _find_the_notion_entry(workspace)
    return [] if entry is None else [entry]


def _show_the_templates(workspace: str | None) -> None:
    entries = _entries_to_show(workspace)
    if not entries:
        where = "" if workspace is None else f" workspace {printable_only(workspace)}"
        print(f"Not signed in to Notion{where}.")
        return
    templates = notion_templates()
    for entry in entries:
        if entry.credentials is None:
            raise AuthError(entry.unreadable_message)
        holder = _template_holder(entry.credentials)
        template = templates.get(str(holder.workspace_id))
        shown = "no page template" if template is None else f"page template {template}"
        name = _workspace_named(entry.credentials.workspace_name)
        print(f"Notion workspace {name} (id {holder.workspace_id}): {shown}")


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


def _sign_in_to_slack(transport: httpx2.BaseTransport | None) -> None:
    refuse_an_unusable_keychain()
    print(
        f"Create a Slack app once at {SLACK_APPS_PAGE}, give it the user token scopes "
        f"{', '.join(SLACK_USER_SCOPES)}, install it to your workspace, and copy its User OAuth Token"
    )
    access_token = _required(
        getpass(f"Slack user token ({SLACK_USER_TOKEN_PREFIX}...): "), "A Slack user token is required"
    )
    credentials = verify_slack_token(access_token, transport=transport)
    save_slack(credentials)
    signed_in = f"{_workspace_named(credentials.team_name)}{_as_user(credentials.user_name)}"
    print(f"Signed in to Slack workspace {signed_in}. Saved to the keychain.")


def _print_status() -> int:
    sections = (
        ("notion", _notion_status_lines),
        ("jira", _jira_status_lines),
        ("slack", _slack_status_lines),
    )
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
    if not _forget_after_the_revoke(entry, revoked):
        outcome = "The Notion token was revoked" if revoked else "The Notion token was not revoked"
        print(f"{outcome}, but a newer sign-in was stored in the meantime and was kept.")
        return
    outcome = "token revoked and removed from the keychain" if revoked else "removed from the keychain"
    print(f"Signed out of Notion: {outcome}.")


def _forget_after_the_revoke(entry: StoredEntry[NotionCredentials], revoked: bool) -> bool:
    try:
        return forget(entry)
    except KeyboardInterrupt:
        if revoked:
            print(
                "warning: the Notion token was revoked, but the logout was interrupted before the keychain "
                "removed its entry, which may remain; run this logout again to remove it",
                file=sys.stderr,
            )
        raise
    except AuthError as unremoved:
        if not revoked:
            raise
        raise AuthError(
            f"The Notion token was revoked, but removing it from the keychain failed ({unremoved}); "
            "run this logout again to remove it"
        ) from unremoved


def _notion_token_was_revoked(
    entry: StoredEntry[NotionCredentials], transport: httpx2.BaseTransport | None
) -> bool:
    if entry.credentials is None:
        print("warning: the stored Notion entry is unreadable, so its token was not revoked", file=sys.stderr)
        return False
    try:
        revoke_notion_token(entry.credentials, transport=transport)
    except AuthError as exc:
        print(
            f"warning: {exc}. If the token was not already revoked, by an earlier logout for example, it is "
            "still valid; remove the connection in Notion under Settings, Connections",
            file=sys.stderr,
        )
        return False
    return True


def _log_out_of_jira(site: str | None) -> None:
    selector, entry = find_jira(site)
    if entry is None:
        where = "" if selector is None else f" at {selector}"
        print(f"Not signed in to Jira{where}.")
        return
    if not forget(entry):
        print("A newer Jira sign-in was stored in the meantime and was kept.")
        return
    print(f"Signed out of Jira: removed from the keychain. Revoke the API token itself at {API_TOKENS_PAGE}")


def _log_out_of_slack(workspace: str | None) -> None:
    entry = find_slack(workspace)
    if entry is None:
        where = "" if workspace is None else f" workspace {printable_only(workspace)}"
        print(f"Not signed in to Slack{where}.")
        return
    if not forget(entry):
        print("A newer Slack sign-in was stored in the meantime and was kept.")
        return
    print(
        "Signed out of Slack: removed from the keychain. Revoke the token itself in your Slack app at "
        f"{SLACK_APPS_PAGE}, under OAuth & Permissions"
    )


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
        _stored_notion_lines,
        "not signed in (run `skaldr auth notion`)",
    )


def _stored_notion_lines() -> list[_StatusLine]:
    entries = stored_notion_sign_ins()
    try:
        templates = notion_templates()
    except AuthError as unreadable:
        return [
            *(_describe_stored_notion(entry, {}) for entry in entries),
            _StatusLine(f"error: {unreadable}", failed=True),
        ]
    return [_describe_stored_notion(entry, templates) for entry in entries]


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


def _slack_status_lines() -> list[_StatusLine]:
    def environment() -> str | None:
        if slack_from_environment() is None:
            return None
        return f"user token from {SLACK_USER_TOKEN_VARIABLE} (environment)"

    return _status_lines(
        environment,
        lambda: [_describe_stored_slack(entry) for entry in stored_slack_sign_ins()],
        "not signed in (run `skaldr auth slack`)",
    )


def _describe_stored_slack(entry: StoredEntry[SlackCredentials]) -> _StatusLine:
    if entry.credentials is None:
        return _StatusLine(f"error: {entry.unreadable_message}", failed=True)
    workspace = _workspace_named(entry.credentials.team_name)
    as_user = _as_user(entry.credentials.user_name)
    return _StatusLine(f"signed in to workspace {workspace} (id {entry.identifier}){as_user} (keychain)")


def _workspace_named(name: str | None) -> str:
    return printable_only(name or "") or _UNNAMED_WORKSPACE


def _as_user(name: str | None) -> str:
    shown = printable_only(name or "")
    return f" as {shown}" if shown else ""


def _describe_stored_notion(
    entry: StoredEntry[NotionCredentials], templates: Mapping[str, str]
) -> _StatusLine:
    if entry.credentials is None:
        return _StatusLine(f"error: {entry.unreadable_message}", failed=True)
    workspace = _workspace_named(entry.credentials.workspace_name)
    template = ""
    if entry.credentials.workspace_id is None:
        identified = f" (no workspace id; name it as {entry.identifier})"
    else:
        identified = f" (id {entry.credentials.workspace_id})"
        if str(entry.credentials.workspace_id) in templates:
            template = f", page template {templates[str(entry.credentials.workspace_id)]}"
    return _StatusLine(f"signed in to workspace {workspace}{identified} (keychain){template}")


def _describe_stored_jira(entry: StoredEntry[JiraCredentials]) -> _StatusLine:
    if entry.credentials is None:
        return _StatusLine(f"error: {entry.unreadable_message}", failed=True)
    display_name = _display_name(entry.credentials)
    if display_name is None:
        return _StatusLine(f"signed in to {entry.credentials.site} (keychain)")
    return _StatusLine(f"signed in to {entry.credentials.site} as {display_name} (keychain)")


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
