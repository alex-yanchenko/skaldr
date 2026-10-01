import pytest

from skaldr.auth.store import (
    JiraCredentials,
    NotionCredentials,
    SignIn,
    forget,
    load_jira,
    load_notion,
    save_jira,
    save_notion,
)
from skaldr.errors import AuthError
from tests.factories.auth_factory import InMemoryKeyring, make_jira_credentials, make_notion_credentials


def test_saved_notion_credentials_load_back_from_the_keychain(keychain: InMemoryKeyring) -> None:
    save_notion(make_notion_credentials())

    assert load_notion() == SignIn(make_notion_credentials(), "keychain")
    assert list(keychain.entries) == [("skaldr", "notion")]


def test_saved_jira_credentials_load_back_from_the_keychain(keychain: InMemoryKeyring) -> None:
    save_jira(make_jira_credentials())

    assert load_jira() == SignIn(make_jira_credentials(), "keychain")
    assert list(keychain.entries) == [("skaldr", "jira")]


def test_nothing_saved_loads_as_signed_out() -> None:
    assert (load_notion(), load_jira()) == (None, None)


def test_a_notion_access_token_in_the_environment_wins_over_the_keychain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_notion(make_notion_credentials())
    monkeypatch.setenv("NOTION_ACCESS_TOKEN", "env-access")
    monkeypatch.setenv("NOTION_REFRESH_TOKEN", "env-refresh")
    monkeypatch.setenv("NOTION_CLIENT_ID", "env-client")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "env-secret")

    assert load_notion() == SignIn(
        NotionCredentials(
            client_id="env-client",
            client_secret="env-secret",
            access_token="env-access",
            refresh_token="env-refresh",
            workspace_name=None,
            bot_id=None,
        ),
        "environment",
    )


def test_a_complete_jira_environment_wins_over_the_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    save_jira(make_jira_credentials())
    monkeypatch.setenv("JIRA_SITE", "https://other.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "ci@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "env-token")

    assert load_jira() == SignIn(
        JiraCredentials(
            site="https://other.atlassian.net",
            email="ci@example.com",
            api_token="env-token",
            display_name=None,
        ),
        "environment",
    )


def test_a_partial_jira_environment_names_the_missing_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_EMAIL", "ci@example.com")

    with pytest.raises(
        AuthError,
        match=r"^JIRA_SITE, JIRA_EMAIL, JIRA_API_TOKEN go together; missing JIRA_SITE, JIRA_API_TOKEN$",
    ):
        load_jira()


def test_an_unreadable_keychain_entry_says_to_sign_in_again(keychain: InMemoryKeyring) -> None:
    keychain.entries[("skaldr", "notion")] = "not json"

    with pytest.raises(AuthError, match="run `skaldr auth notion` again"):
        load_notion()


def test_forget_deletes_the_entry_and_reports_whether_one_existed(keychain: InMemoryKeyring) -> None:
    save_jira(make_jira_credentials())

    assert (forget("jira"), forget("jira")) == (True, False)
    assert keychain.entries == {}
