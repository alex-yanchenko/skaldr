import sys

import httpx2
import pytest

from skaldr.auth import cli as auth_cli
from skaldr.auth.store import SignIn, load_jira, load_notion, save_jira, save_notion
from skaldr.cli import main
from tests.factories.auth_factory import (
    TOKEN_RESPONSE,
    FakeBrowser,
    InMemoryKeyring,
    approving,
    fake_api,
    make_jira_credentials,
    make_notion_credentials,
)

MYSELF = {"accountId": "account-id", "displayName": "Example Reader"}


def answer_prompts(monkeypatch: pytest.MonkeyPatch, typed: list[str], hidden: list[str]) -> None:
    def next_typed(_prompt: str) -> str:
        return typed.pop(0)

    def next_hidden(_prompt: str) -> str:
        return hidden.pop(0)

    monkeypatch.setattr("builtins.input", next_typed)
    monkeypatch.setattr(auth_cli, "getpass", next_hidden)


def refuse_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(prompt: str) -> str:
        pytest.fail(f"prompted for {prompt!r}")

    monkeypatch.setattr("builtins.input", fail)
    monkeypatch.setattr(auth_cli, "getpass", fail)


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


def test_auth_notion_prompts_for_the_client_signs_in_and_saves(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    typed = ["client-id"]
    hidden = ["client-secret"]
    answer_prompts(monkeypatch, typed, hidden)
    browser = FakeBrowser(approving)

    exit_code = auth_cli.main(
        ["notion", "--port", "0"],
        transport=fake_api({"/v1/oauth/token": (200, TOKEN_RESPONSE)}, []),
        open_browser=browser,
    )

    assert (exit_code, typed, hidden) == (0, [], [])
    assert load_notion() == SignIn(
        make_notion_credentials(access_token="new-access", refresh_token="new-refresh"), "keychain"
    )
    assert capsys.readouterr().out == (
        "Register a public Notion connection once at https://www.notion.so/profile/integrations, "
        "with redirect URI http://localhost:0/callback\n"
        f"Opening Notion in your browser. If it does not open, visit:\n  {browser.opened[0]}\n"
        "Signed in to Notion workspace Example Workspace. Saved to the keychain.\n"
    )


def test_auth_notion_takes_the_client_from_the_environment_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTION_CLIENT_ID", "client-id")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "client-secret")
    refuse_prompts(monkeypatch)

    exit_code = auth_cli.main(
        ["notion", "--port", "0"],
        transport=fake_api({"/v1/oauth/token": (200, TOKEN_RESPONSE)}, []),
        open_browser=FakeBrowser(approving),
    )

    assert exit_code == 0


def test_auth_notion_refuses_an_empty_client_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answer_prompts(monkeypatch, ["  "], [])

    assert auth_cli.main(["notion"]) == 1
    assert capsys.readouterr().err == "error: A Notion OAuth client ID is required\n"


def test_status_with_nobody_signed_in(capsys: pytest.CaptureFixture[str]) -> None:
    assert auth_cli.main(["status"]) == 0
    assert capsys.readouterr().out == (
        "notion  not signed in (run `skaldr auth notion`)\njira    not signed in (run `skaldr auth jira`)\n"
    )


def test_status_names_who_is_signed_in_from_the_keychain(capsys: pytest.CaptureFixture[str]) -> None:
    save_notion(make_notion_credentials())
    save_jira(make_jira_credentials())

    assert auth_cli.main(["status"]) == 0
    assert capsys.readouterr().out == (
        "notion  signed in to workspace Example Workspace (keychain)\n"
        "jira    signed in to https://example.atlassian.net as Example Reader (keychain)\n"
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
        "jira    ci@example.com at https://example.atlassian.net (environment)\n"
    )


def test_logout_notion_revokes_the_token_and_forgets_it(
    keychain: InMemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    save_notion(make_notion_credentials())
    seen: list[httpx2.Request] = []

    exit_code = auth_cli.main(["logout", "notion"], transport=fake_api({"/v1/oauth/revoke": (200, {})}, seen))

    assert (exit_code, keychain.entries, len(seen)) == (0, {}, 1)
    assert capsys.readouterr().out == "Signed out of Notion: token revoked and removed from the keychain.\n"


def test_logout_notion_still_forgets_a_token_notion_would_not_revoke(
    keychain: InMemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    save_notion(make_notion_credentials())

    exit_code = auth_cli.main(["logout", "notion"], transport=fake_api({"/v1/oauth/revoke": (400, {})}, []))

    assert (exit_code, keychain.entries) == (0, {})
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == (
        "Signed out of Notion: removed from the keychain.\n",
        "warning: Notion did not revoke the token: HTTP 400\n",
    )


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
def test_logout_when_signed_out_says_so(service: str, name: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert auth_cli.main(["logout", service]) == 0
    assert capsys.readouterr().out == f"Not signed in to {name}.\n"


def test_skaldr_auth_dispatches_to_the_auth_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["auth", "status"]) == 0
    assert capsys.readouterr().out.startswith("notion  not signed in")


def test_skaldr_auth_without_the_publish_extra_names_the_install_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for module in [name for name in sys.modules if name.startswith("skaldr.auth")]:
        monkeypatch.delitem(sys.modules, module)
    for module in [name for name in sys.modules if name == "authlib" or name.startswith("authlib.")]:
        monkeypatch.setitem(sys.modules, module, None)
    monkeypatch.setitem(sys.modules, "authlib", None)

    assert main(["auth", "status"]) == 1
    assert capsys.readouterr().err == (
        "error: `skaldr auth` needs the publish extra: pip install 'skaldr[publish]'\n"
    )
