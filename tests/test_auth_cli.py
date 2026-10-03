import builtins
import re
import socket
import sys
from types import ModuleType
from typing import Any, NoReturn

import httpx2
import keyring
import pytest

from skaldr.auth import cli as auth_cli
from skaldr.auth.store import Service, SignIn, load_jira, load_notion, save_jira, save_notion
from skaldr.cli import main
from tests.factories.auth_factory import (
    MYSELF,
    TOKEN_RESPONSE,
    FakeBrowser,
    InMemoryKeyring,
    LockedKeyring,
    PlaintextKeyring,
    WriteRefusingKeyring,
    approving,
    basic_auth_header,
    fake_api,
    free_port,
    insecure_keyring_refusal,
    make_jira_credentials,
    make_notion_credentials,
    summarise,
)

SIGNED_IN_NOTION = make_notion_credentials(access_token="new-access", refresh_token="new-refresh")


def answer_prompts(monkeypatch: pytest.MonkeyPatch, typed: list[str], hidden: list[str]) -> None:
    def next_typed(_prompt: str) -> str:
        return typed.pop(0)

    def next_hidden(_prompt: str) -> str:
        return hidden.pop(0)

    monkeypatch.setattr("builtins.input", next_typed)
    monkeypatch.setattr(auth_cli, "getpass", next_hidden)


def refuse_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(prompt: str) -> NoReturn:
        pytest.fail(f"prompted for {prompt!r}")

    monkeypatch.setattr("builtins.input", fail)
    monkeypatch.setattr(auth_cli, "getpass", fail)


def notion_client_in_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTION_CLIENT_ID", "client-id")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "client-secret")


def test_auth_jira_verifies_the_token_and_saves_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    typed = ["example.atlassian.net", "reader@example.com"]
    hidden = ["api-token"]
    answer_prompts(monkeypatch, typed, hidden)
    seen: list[httpx2.Request] = []

    exit_code = auth_cli.main(["jira"], transport=fake_api({"/rest/api/3/myself": (200, MYSELF)}, seen))

    assert (exit_code, typed, hidden, len(seen)) == (0, [], [], 1)
    assert load_jira() == SignIn(make_jira_credentials(), "keychain")
    assert capsys.readouterr().out == (
        "Signed in to Jira at https://example.atlassian.net as Example Reader. Saved to the keychain.\n"
    )


@pytest.mark.parametrize(
    "display_name", ["", "\x1b\x07\r\n"], ids=["empty", "nothing but control characters"]
)
def test_auth_jira_leaves_out_a_display_name_it_cannot_show(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], display_name: str
) -> None:
    answer_prompts(monkeypatch, ["example.atlassian.net", "reader@example.com"], ["api-token"])
    myself = {**MYSELF, "displayName": display_name}

    exit_code = auth_cli.main(["jira"], transport=fake_api({"/rest/api/3/myself": (200, myself)}, []))

    assert (exit_code, capsys.readouterr().out) == (
        0,
        "Signed in to Jira at https://example.atlassian.net. Saved to the keychain.\n",
    )


def test_auth_jira_prints_only_the_printable_part_of_the_display_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answer_prompts(monkeypatch, ["example.atlassian.net", "reader@example.com"], ["api-token"])
    myself = {**MYSELF, "displayName": "Example\x1b[2J Reader\x07\r\n"}

    exit_code = auth_cli.main(["jira"], transport=fake_api({"/rest/api/3/myself": (200, myself)}, []))

    assert (exit_code, capsys.readouterr().out) == (
        0,
        "Signed in to Jira at https://example.atlassian.net as Example[2J Reader. Saved to the keychain.\n",
    )


def test_auth_jira_saves_nothing_when_the_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch, keychain: InMemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    answer_prompts(monkeypatch, ["https://example.atlassian.net", "reader@example.com"], ["wrong-token"])

    exit_code = auth_cli.main(["jira"], transport=fake_api({"/rest/api/3/myself": (401, {})}, []))

    assert (exit_code, keychain.entries) == (1, {})
    assert capsys.readouterr().err == (
        "error: Jira rejected the email and API token (HTTP 401). Check both, or create a new token at "
        "https://id.atlassian.com/manage-profile/security/api-tokens\n"
    )


@pytest.mark.parametrize(
    ("typed", "hidden", "error"),
    [
        (
            ["http://example.atlassian.net"],
            [],
            "The Jira site must be an https URL like https://<site>.atlassian.net, not 'http://example.atlassian.net'",
        ),
        (["example.atlassian.net", " "], [], "An Atlassian account email is required"),
        (["example.atlassian.net", "reader@example.com"], [""], "An API token is required"),
    ],
    ids=["http site", "blank email", "blank token"],
)
def test_auth_jira_refuses_a_bad_answer_before_calling_jira(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    typed: list[str],
    hidden: list[str],
    error: str,
) -> None:
    answer_prompts(monkeypatch, typed, hidden)
    seen: list[httpx2.Request] = []

    assert auth_cli.main(["jira"], transport=fake_api({}, seen)) == 1
    assert (capsys.readouterr().err, seen) == (f"error: {error}\n", [])


def test_auth_notion_prompts_for_the_client_signs_in_and_saves(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    typed = ["client-id"]
    hidden = ["client-secret"]
    answer_prompts(monkeypatch, typed, hidden)
    browser = FakeBrowser(approving)
    port = free_port()

    exit_code = auth_cli.main(
        ["notion", "--port", str(port)],
        transport=fake_api({"/v1/oauth/token": (200, TOKEN_RESPONSE)}, []),
        open_browser=browser,
    )

    assert (exit_code, typed, hidden, browser.finished()) == (0, [], [], [200])
    assert load_notion() == SignIn(SIGNED_IN_NOTION, "keychain")
    assert capsys.readouterr().out == (
        "Register a public Notion connection once at https://www.notion.so/profile/integrations, "
        f"with redirect URI http://localhost:{port}/callback\n"
        f"Opening Notion in your browser. If it does not open, visit:\n  {browser.opened[0]}\n"
        "Signed in to Notion workspace Example Workspace. Saved to the keychain.\n"
    )


def test_auth_notion_takes_the_client_from_the_environment_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notion_client_in_environment(monkeypatch)
    refuse_prompts(monkeypatch)
    browser = FakeBrowser(approving)

    exit_code = auth_cli.main(
        ["notion", "--port", str(free_port())],
        transport=fake_api({"/v1/oauth/token": (200, TOKEN_RESPONSE)}, []),
        open_browser=browser,
    )

    assert (exit_code, browser.finished()) == (0, [200])
    assert load_notion() == SignIn(SIGNED_IN_NOTION, "keychain")


def test_auth_notion_names_a_workspace_notion_left_unnamed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    notion_client_in_environment(monkeypatch)
    browser = FakeBrowser(approving)

    exit_code = auth_cli.main(
        ["notion", "--port", str(free_port())],
        transport=fake_api({"/v1/oauth/token": (200, {**TOKEN_RESPONSE, "workspace_name": None})}, []),
        open_browser=browser,
    )

    assert (exit_code, browser.finished()) == (0, [200])
    assert capsys.readouterr().out.endswith(
        "Signed in to Notion workspace (unnamed workspace). Saved to the keychain.\n"
    )


def test_auth_notion_prints_only_the_printable_part_of_the_workspace_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    notion_client_in_environment(monkeypatch)
    browser = FakeBrowser(approving)
    token = {**TOKEN_RESPONSE, "workspace_name": "Example\x1b[2J\N{RIGHT-TO-LEFT OVERRIDE} Workspace\r\n"}

    exit_code = auth_cli.main(
        ["notion", "--port", str(free_port())],
        transport=fake_api({"/v1/oauth/token": (200, token)}, []),
        open_browser=browser,
    )

    assert (exit_code, browser.finished()) == (0, [200])
    assert capsys.readouterr().out.endswith(
        "Signed in to Notion workspace Example[2J Workspace. Saved to the keychain.\n"
    )


@pytest.mark.parametrize(
    ("variable", "typed", "hidden"),
    [("NOTION_CLIENT_ID", [], ["client-secret"]), ("NOTION_CLIENT_SECRET", ["client-id"], [])],
    ids=["client id from the environment", "client secret from the environment"],
)
def test_auth_notion_prompts_only_for_what_the_environment_lacks(
    monkeypatch: pytest.MonkeyPatch, variable: str, typed: list[str], hidden: list[str]
) -> None:
    monkeypatch.setenv(variable, "client-id" if variable == "NOTION_CLIENT_ID" else "client-secret")
    answer_prompts(monkeypatch, typed, hidden)
    browser = FakeBrowser(approving)

    exit_code = auth_cli.main(
        ["notion", "--port", str(free_port())],
        transport=fake_api({"/v1/oauth/token": (200, TOKEN_RESPONSE)}, []),
        open_browser=browser,
    )

    assert (exit_code, typed, hidden, browser.finished()) == (0, [], [], [200])
    assert load_notion() == SignIn(SIGNED_IN_NOTION, "keychain")


def test_auth_notion_refuses_a_client_secret_with_characters_outside_ascii(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answer_prompts(monkeypatch, ["client-id"], ["secret\N{RIGHT SINGLE QUOTATION MARK}"])

    assert auth_cli.main(["notion"]) == 1
    assert capsys.readouterr().err == (
        "error: The Notion OAuth client secret has characters outside ASCII; copy it from Notion again\n"
    )


def test_auth_notion_reports_a_locked_keychain_before_listening_or_opening_the_browser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    notion_client_in_environment(monkeypatch)
    keyring.set_keyring(LockedKeyring())
    browser = FakeBrowser(approving)
    seen: list[httpx2.Request] = []

    with socket.create_server(("127.0.0.1", 0)) as blocker:
        port = blocker.getsockname()[1]
        exit_code = auth_cli.main(
            ["notion", "--port", str(port)], transport=fake_api({}, seen), open_browser=browser
        )

    assert (exit_code, capsys.readouterr().err, browser.opened, seen) == (
        1,
        "error: The system keychain is unavailable: locked\n",
        [],
        [],
    )


NOTION_REVOKE_OF_THE_NEW_TOKEN = {
    "method": "POST",
    "url": "https://api.notion.com/v1/oauth/revoke",
    "authorization": basic_auth_header("client-id", "client-secret"),
    "content_type": "application/json",
    "body": {"token": "new-access"},
}


@pytest.mark.parametrize(
    ("revoke_status", "error"),
    [
        (200, "The system keychain is unavailable: denied"),
        (
            400,
            "The system keychain is unavailable: denied. The token Notion just issued could not be saved, "
            "and revoking it failed too (Notion did not revoke the token: HTTP 400), so remove the "
            "connection in Notion under Settings, Connections",
        ),
    ],
    ids=["the revoke succeeds", "the revoke fails too"],
)
def test_auth_notion_revokes_a_token_the_keychain_refuses_to_save(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], revoke_status: int, error: str
) -> None:
    notion_client_in_environment(monkeypatch)
    keyring.set_keyring(WriteRefusingKeyring())
    browser = FakeBrowser(approving)
    seen: list[httpx2.Request] = []
    routes: dict[str, tuple[int, object]] = {
        "/v1/oauth/token": (200, TOKEN_RESPONSE),
        "/v1/oauth/revoke": (revoke_status, {}),
    }

    exit_code = auth_cli.main(
        ["notion", "--port", str(free_port())], transport=fake_api(routes, seen), open_browser=browser
    )

    revokes = [summarise(request) for request in seen if request.url.path == "/v1/oauth/revoke"]
    assert (exit_code, browser.finished(), revokes, capsys.readouterr().err) == (
        1,
        [200],
        [NOTION_REVOKE_OF_THE_NEW_TOKEN],
        f"error: {error}\n",
    )


def test_auth_jira_reports_a_locked_keychain_before_asking_for_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    keyring.set_keyring(LockedKeyring())
    refuse_prompts(monkeypatch)
    seen: list[httpx2.Request] = []

    exit_code = auth_cli.main(["jira"], transport=fake_api({}, seen))

    assert (exit_code, capsys.readouterr().err, seen) == (
        1,
        "error: The system keychain is unavailable: locked\n",
        [],
    )


@pytest.mark.parametrize(
    ("typed", "hidden", "error"),
    [
        (["  "], [], "A Notion OAuth client ID is required"),
        (["client-id"], [" "], "A Notion OAuth client secret is required"),
    ],
    ids=["blank client id", "blank client secret"],
)
def test_auth_notion_refuses_a_blank_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    typed: list[str],
    hidden: list[str],
    error: str,
) -> None:
    answer_prompts(monkeypatch, typed, hidden)

    assert auth_cli.main(["notion"]) == 1
    assert capsys.readouterr().err == f"error: {error}\n"


@pytest.fixture
def plaintext() -> PlaintextKeyring:
    backend = PlaintextKeyring()
    keyring.set_keyring(backend)
    return backend


@pytest.mark.parametrize(
    "client_in_environment", [False, True], ids=["client to prompt for", "client from the environment"]
)
def test_auth_notion_refuses_an_insecure_keyring_before_prompting_listening_or_opening_the_browser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    plaintext: PlaintextKeyring,
    client_in_environment: bool,
) -> None:
    if client_in_environment:
        notion_client_in_environment(monkeypatch)
    refuse_prompts(monkeypatch)
    browser = FakeBrowser(approving)
    seen: list[httpx2.Request] = []

    with socket.create_server(("127.0.0.1", 0)) as blocker:
        port = blocker.getsockname()[1]
        exit_code = auth_cli.main(
            ["notion", "--port", str(port)], transport=fake_api({}, seen), open_browser=browser
        )

    assert (exit_code, capsys.readouterr().err, browser.opened, seen, plaintext.entries) == (
        1,
        f"error: {insecure_keyring_refusal('keyrings.alt.file.PlaintextKeyring')}\n",
        [],
        [],
        {},
    )


def test_auth_jira_refuses_an_insecure_keyring_before_asking_for_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], plaintext: PlaintextKeyring
) -> None:
    refuse_prompts(monkeypatch)
    seen: list[httpx2.Request] = []

    exit_code = auth_cli.main(["jira"], transport=fake_api({}, seen))

    assert (exit_code, capsys.readouterr().err, seen, plaintext.entries) == (
        1,
        f"error: {insecure_keyring_refusal('keyrings.alt.file.PlaintextKeyring')}\n",
        [],
        {},
    )


def test_auth_notion_names_a_busy_port(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    notion_client_in_environment(monkeypatch)

    with socket.create_server(("127.0.0.1", 0)) as blocker:
        port = blocker.getsockname()[1]
        assert auth_cli.main(["notion", "--port", str(port)], open_browser=FakeBrowser()) == 1

    assert re.fullmatch(
        rf"error: Cannot listen on 127\.0\.0\.1:{port} \(.+\); free the port, or register a redirect URI "
        r"with another port and pass it with --port\n",
        capsys.readouterr().err,
    )


@pytest.mark.parametrize("port", ["0", "65536", "eighty"])
def test_auth_notion_refuses_a_port_outside_tcp(port: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        auth_cli.main(["notion", "--port", port])

    assert exited.value.code == 2
    assert f"argument --port: '{port}' is not a TCP port (1 to 65535)" in capsys.readouterr().err


@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_a_cancelled_prompt_ends_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], interruption: type[BaseException]
) -> None:
    def interrupt(_prompt: str) -> NoReturn:
        raise interruption

    monkeypatch.setattr("builtins.input", interrupt)

    assert auth_cli.main(["jira"]) == 1
    assert capsys.readouterr().err == "\nerror: cancelled\n"


def test_status_with_nobody_signed_in(capsys: pytest.CaptureFixture[str]) -> None:
    assert auth_cli.main(["status"]) == 0
    assert capsys.readouterr().out == (
        "notion  not signed in (run `skaldr auth notion`)\njira    not signed in (run `skaldr auth jira`)\n"
    )


def test_status_names_who_is_signed_in_from_the_keychain(capsys: pytest.CaptureFixture[str]) -> None:
    save_notion(make_notion_credentials(workspace_name=None))
    save_jira(make_jira_credentials(display_name=None))

    assert auth_cli.main(["status"]) == 0
    assert capsys.readouterr().out == (
        "notion  signed in to workspace (unnamed workspace) (keychain)\n"
        "jira    signed in to https://example.atlassian.net (keychain)\n"
    )


def test_status_prints_only_the_printable_part_of_stored_names(capsys: pytest.CaptureFixture[str]) -> None:
    save_notion(make_notion_credentials(workspace_name="Example\x1b[2J Workspace"))
    save_jira(make_jira_credentials(display_name="Example\x1b]0;title\x07 Reader"))

    assert auth_cli.main(["status"]) == 0
    assert capsys.readouterr().out == (
        "notion  signed in to workspace Example[2J Workspace (keychain)\n"
        "jira    signed in to https://example.atlassian.net as Example]0;title Reader (keychain)\n"
    )


def test_status_names_credentials_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOTION_ACCESS_TOKEN", "env-access")
    monkeypatch.setenv("JIRA_SITE", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "ci@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "env-token")

    assert auth_cli.main(["status"]) == 0
    assert capsys.readouterr().out == (
        "notion  access token from NOTION_ACCESS_TOKEN (environment)\n"
        "jira    JIRA_EMAIL, JIRA_API_TOKEN for https://example.atlassian.net (environment)\n"
    )


def test_status_reports_jira_even_when_notion_is_broken(
    keychain: InMemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    keychain.entries[("skaldr", "notion")] = "not json"
    save_jira(make_jira_credentials())

    assert auth_cli.main(["status"]) == 1
    assert capsys.readouterr().out == (
        "notion  error: The keychain entry for notion is unreadable; run `skaldr auth notion` again\n"
        "jira    signed in to https://example.atlassian.net as Example Reader (keychain)\n"
    )


def test_status_reports_notion_even_when_jira_is_broken(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    save_notion(make_notion_credentials())
    monkeypatch.setenv("JIRA_EMAIL", "ci@example.com")

    assert auth_cli.main(["status"]) == 1
    assert capsys.readouterr().out == (
        "notion  signed in to workspace Example Workspace (keychain)\n"
        "jira    error: JIRA_SITE, JIRA_EMAIL, JIRA_API_TOKEN go together; "
        "missing JIRA_SITE, JIRA_API_TOKEN\n"
    )


def test_logout_notion_revokes_the_token_and_forgets_it(
    keychain: InMemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    save_notion(make_notion_credentials())
    seen: list[httpx2.Request] = []

    exit_code = auth_cli.main(["logout", "notion"], transport=fake_api({"/v1/oauth/revoke": (200, {})}, seen))

    assert (exit_code, keychain.entries, len(seen)) == (0, {}, 1)
    assert capsys.readouterr().out == "Signed out of Notion: token revoked and removed from the keychain.\n"


@pytest.mark.parametrize(
    ("stored", "warning"),
    [
        (make_notion_credentials().model_dump_json(), "Notion did not revoke the token: HTTP 400"),
        (
            make_notion_credentials(client_id=None).model_dump_json(),
            "The Notion token cannot be revoked without the client ID and secret",
        ),
        ("not json", "the stored Notion entry is unreadable, so its token was not revoked"),
    ],
    ids=["revoke refused", "no client", "unreadable entry"],
)
def test_logout_notion_still_forgets_a_token_it_could_not_revoke(
    keychain: InMemoryKeyring, capsys: pytest.CaptureFixture[str], stored: str, warning: str
) -> None:
    keychain.entries[("skaldr", "notion")] = stored

    exit_code = auth_cli.main(["logout", "notion"], transport=fake_api({"/v1/oauth/revoke": (400, {})}, []))

    assert (exit_code, keychain.entries) == (0, {})
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == (
        "Signed out of Notion: removed from the keychain.\n",
        f"warning: {warning}\n",
    )


@pytest.mark.parametrize("service", ["notion", "jira"])
def test_logout_reports_a_locked_keychain_once(service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    keyring.set_keyring(LockedKeyring())

    assert auth_cli.main(["logout", service]) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "error: The system keychain is unavailable: locked\n")


def test_logout_jira_forgets_the_token_and_points_at_revoking_it(
    keychain: InMemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    save_jira(make_jira_credentials())

    assert auth_cli.main(["logout", "jira"]) == 0
    assert keychain.entries == {}
    assert capsys.readouterr().out == (
        "Signed out of Jira: removed from the keychain. Revoke the API token itself at "
        "https://id.atlassian.com/manage-profile/security/api-tokens\n"
    )


@pytest.mark.parametrize(("service", "name"), [("notion", "Notion"), ("jira", "Jira")])
def test_logout_when_signed_out_says_so(
    service: Service, name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert auth_cli.main(["logout", service]) == 0
    assert capsys.readouterr().out == f"Not signed in to {name}.\n"


NOBODY_SIGNED_IN = (
    "notion  not signed in (run `skaldr auth notion`)\njira    not signed in (run `skaldr auth jira`)\n"
)


def test_skaldr_auth_dispatches_to_the_auth_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["auth", "status"]) == 0
    assert capsys.readouterr().out == NOBODY_SIGNED_IN


def test_skaldr_auth_reads_the_command_line_when_given_no_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["skaldr", "auth", "status"])

    assert main() == 0
    assert capsys.readouterr().out == NOBODY_SIGNED_IN


def hide_modules(monkeypatch: pytest.MonkeyPatch, root: str) -> None:
    for module in [name for name in sys.modules if name.startswith("skaldr.auth")]:
        monkeypatch.delitem(sys.modules, module)
    for module in [name for name in sys.modules if name.startswith(f"{root}.")]:
        monkeypatch.setitem(sys.modules, module, None)
    monkeypatch.setitem(sys.modules, root, None)


@pytest.mark.parametrize("missing", ["authlib", "httpx2", "keyring"])
def test_skaldr_auth_without_the_publish_extra_names_the_install_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    hide_modules(monkeypatch, missing)

    assert main(["auth", "status"]) == 1
    assert capsys.readouterr().err == (
        f"error: `skaldr auth` needs the publish extra ({missing} is not installed). Reinstall with it: "
        "uv tool install --force 'skaldr[publish]', pipx install --force 'skaldr[publish]', "
        "or pip install 'skaldr[publish]'\n"
    )


def test_a_missing_skaldr_module_is_a_bug_and_not_a_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    hide_modules(monkeypatch, "skaldr.auth.store")

    with pytest.raises(ModuleNotFoundError, match=r"skaldr\.auth\.store"):
        main(["auth", "status"])


def test_an_import_failure_that_names_no_module_is_a_bug_and_not_a_missing_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def failing_import(name: str, *args: Any, **kwargs: Any) -> ModuleType:
        if name == "skaldr.auth.cli":
            raise ModuleNotFoundError("broken install")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)

    with pytest.raises(ModuleNotFoundError, match=r"^broken install$"):
        main(["auth", "status"])


def test_skaldr_help_points_at_the_auth_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])

    assert (
        "Sign in to Notion or Jira with `skaldr auth`; see `skaldr auth --help`." in capsys.readouterr().out
    )
