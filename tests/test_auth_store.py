import json
import time
from collections.abc import Callable

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail, null
from keyring.backends.chainer import ChainerBackend
from pydantic import ValidationError

from skaldr.auth import store
from skaldr.auth.store import (
    JiraCredentials,
    NotionCredentials,
    SignIn,
    StoredEntry,
    forget,
    jira_credentials,
    load_jira,
    load_notion,
    normalise_site,
    refuse_an_unusable_keychain,
    require_jira,
    require_notion,
    save_jira,
    save_notion,
    stored_jira_sign_ins,
    stored_notion_replaced_by,
    stored_notion_sign_ins,
)
from skaldr.errors import AuthError
from tests.factories.auth_factory import (
    SITE_REFUSALS,
    SITE_WITH_A_PASSWORD,
    SITES_OFF_JIRA_CLOUD,
    InMemoryKeyring,
    LockedKeyring,
    NullKeyringSubclass,
    PlaintextKeyring,
    PlaintextKeyringSubclass,
    ReadRecordingKeyring,
    SlowKeyring,
    assert_secret_not_in_error_chain,
    insecure_keyring_refusal,
    legacy_entry_json,
    make_jira_credentials,
    make_notion_credentials,
)

AN_ENTRY = StoredEntry[JiraCredentials]("jira", "jira:https://example.atlassian.net", None)
WAITING_FOR_THE_KEYCHAIN = (
    "Waiting for the system keychain; if it is locked or shows a prompt for skaldr, "
    "unlock it or answer there.\n"
)


def index_of(*, jira: list[str] | None = None, notion: list[str] | None = None) -> str:
    return json.dumps({"jira": jira or [], "notion": notion or []})


def test_saved_notion_credentials_load_back_from_the_keychain(keychain: InMemoryKeyring) -> None:
    save_notion(make_notion_credentials())

    assert load_notion() == SignIn(make_notion_credentials(), "keychain")
    assert keychain.entries == {
        ("skaldr", "notion:workspace-id"): make_notion_credentials().model_dump_json(),
        ("skaldr", "index"): index_of(notion=["notion:workspace-id"]),
    }


def test_saved_jira_credentials_load_back_from_the_keychain(keychain: InMemoryKeyring) -> None:
    save_jira(make_jira_credentials())

    assert load_jira() == SignIn(make_jira_credentials(), "keychain")
    assert keychain.entries == {
        ("skaldr", "jira:https://example.atlassian.net"): make_jira_credentials().model_dump_json(),
        ("skaldr", "index"): index_of(jira=["jira:https://example.atlassian.net"]),
    }


def test_a_second_jira_site_is_kept_beside_the_first(keychain: InMemoryKeyring) -> None:
    other = make_jira_credentials(site="https://other.atlassian.net", api_token="other-token")
    save_jira(make_jira_credentials())
    save_jira(other)

    assert stored_jira_sign_ins() == [
        StoredEntry("jira", "jira:https://example.atlassian.net", make_jira_credentials()),
        StoredEntry("jira", "jira:https://other.atlassian.net", other),
    ]
    assert keychain.entries[("skaldr", "index")] == index_of(
        jira=["jira:https://example.atlassian.net", "jira:https://other.atlassian.net"]
    )


def test_saving_a_jira_site_again_replaces_only_that_site() -> None:
    other = make_jira_credentials(site="https://other.atlassian.net")
    replacement = make_jira_credentials(api_token="replacement-token")
    save_jira(make_jira_credentials())
    save_jira(other)

    save_jira(replacement)

    assert [entry.credentials for entry in stored_jira_sign_ins()] == [replacement, other]


def test_a_second_notion_workspace_is_kept_beside_the_first() -> None:
    other = make_notion_credentials(workspace_id="other-id", workspace_name="Other Workspace")
    save_notion(make_notion_credentials())
    save_notion(other)

    assert stored_notion_sign_ins() == [
        StoredEntry("notion", "notion:workspace-id", make_notion_credentials()),
        StoredEntry("notion", "notion:other-id", other),
    ]


def test_saving_a_notion_workspace_again_replaces_only_that_workspace() -> None:
    other = make_notion_credentials(workspace_id="other-id", workspace_name="Other Workspace")
    replacement = make_notion_credentials(access_token="replacement-access")
    save_notion(make_notion_credentials())
    save_notion(other)

    save_notion(replacement)

    assert [entry.credentials for entry in stored_notion_sign_ins()] == [replacement, other]


def test_an_entry_missing_from_the_keychain_but_named_in_the_index_is_skipped(
    keychain: InMemoryKeyring,
) -> None:
    save_jira(make_jira_credentials())
    del keychain.entries[("skaldr", "jira:https://example.atlassian.net")]

    assert stored_jira_sign_ins() == []


def test_the_only_stored_jira_sign_in_is_found_without_naming_its_site() -> None:
    save_jira(make_jira_credentials())

    assert load_jira() == SignIn(make_jira_credentials(), "keychain")


def test_a_jira_site_names_the_sign_in_to_find() -> None:
    other = make_jira_credentials(site="https://other.atlassian.net")
    save_jira(make_jira_credentials())
    save_jira(other)

    assert (load_jira("Other.atlassian.net/jira"), load_jira("https://example.atlassian.net")) == (
        SignIn(other, "keychain"),
        SignIn(make_jira_credentials(), "keychain"),
    )


def test_a_jira_site_nobody_signed_in_to_finds_nothing() -> None:
    save_jira(make_jira_credentials())

    assert load_jira("https://unknown.atlassian.net") is None


def test_several_jira_sites_without_a_named_site_are_refused_with_the_choices() -> None:
    save_jira(make_jira_credentials())
    save_jira(make_jira_credentials(site="https://other.atlassian.net"))

    with pytest.raises(AuthError) as raised:
        load_jira()

    assert str(raised.value) == (
        "Signed in to several Jira sites (https://example.atlassian.net, https://other.atlassian.net); "
        "name one"
    )


def test_an_unreadable_legacy_entry_counts_as_a_sign_in_when_no_site_is_named(
    keychain: InMemoryKeyring,
) -> None:
    keychain.entries[("skaldr", "jira")] = "not json"
    save_jira(make_jira_credentials())

    with pytest.raises(AuthError) as raised:
        load_jira()

    assert str(raised.value) == (
        "Signed in to several Jira sites (https://example.atlassian.net, an unreadable entry); name one"
    )


def test_a_jira_site_that_is_not_a_jira_cloud_origin_is_refused_as_a_selector() -> None:
    with pytest.raises(AuthError, match=r"^The Jira site must be an https URL"):
        load_jira("https://evil.example")


def test_the_jira_environment_answers_for_its_own_site_and_the_keychain_for_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = make_jira_credentials(site="https://other.atlassian.net")
    save_jira(stored)
    monkeypatch.setenv("JIRA_SITE", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "ci@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "env-token")

    from_environment = load_jira("https://example.atlassian.net")
    from_keychain = load_jira("https://other.atlassian.net")

    assert from_environment is not None
    assert (from_environment.source, from_environment.credentials.api_token, from_keychain) == (
        "environment",
        "env-token",
        SignIn(stored, "keychain"),
    )


def test_the_only_stored_notion_sign_in_is_found_without_naming_a_workspace() -> None:
    save_notion(make_notion_credentials())

    assert load_notion() == SignIn(make_notion_credentials(), "keychain")


def test_a_notion_workspace_is_found_by_its_id_or_its_name() -> None:
    other = make_notion_credentials(workspace_id="other-id", workspace_name="Other Workspace")
    save_notion(make_notion_credentials())
    save_notion(other)

    assert (load_notion("other-id"), load_notion("Other Workspace"), load_notion("workspace-id")) == (
        SignIn(other, "keychain"),
        SignIn(other, "keychain"),
        SignIn(make_notion_credentials(), "keychain"),
    )


def test_a_notion_workspace_nobody_signed_in_to_finds_nothing() -> None:
    save_notion(make_notion_credentials())

    assert load_notion("unknown-id") is None


def test_several_notion_workspaces_without_a_named_workspace_are_refused_with_the_choices() -> None:
    save_notion(make_notion_credentials())
    save_notion(make_notion_credentials(workspace_id="other-id", workspace_name=None))

    with pytest.raises(AuthError) as raised:
        load_notion()

    assert str(raised.value) == (
        "Signed in to several Notion workspaces (Example Workspace (workspace-id), other-id); name one"
    )


def test_two_workspaces_with_one_name_are_refused_when_the_name_is_the_selector() -> None:
    save_notion(make_notion_credentials())
    save_notion(make_notion_credentials(workspace_id="other-id"))

    with pytest.raises(AuthError) as raised:
        load_notion("Example Workspace")

    assert str(raised.value) == (
        "Signed in to several Notion workspaces (Example Workspace (workspace-id), "
        "Example Workspace (other-id)); name one"
    )


def test_a_notion_access_token_in_the_environment_is_skipped_when_a_workspace_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_notion(make_notion_credentials())
    monkeypatch.setenv("NOTION_ACCESS_TOKEN", "env-access")

    assert load_notion("workspace-id") == SignIn(make_notion_credentials(), "keychain")


@pytest.mark.parametrize(
    ("find", "refusal"),
    [
        (lambda: require_jira(), "Not signed in to Jira; run `skaldr auth jira`"),
        (
            lambda: require_jira("example.atlassian.net"),
            "Not signed in to Jira at https://example.atlassian.net; run `skaldr auth jira`",
        ),
        (lambda: require_notion(), "Not signed in to Notion; run `skaldr auth notion`"),
        (
            lambda: require_notion("workspace-id"),
            "Not signed in to Notion workspace workspace-id; run `skaldr auth notion`",
        ),
    ],
    ids=["jira", "a jira site", "notion", "a notion workspace"],
)
def test_requiring_a_sign_in_that_is_not_there_says_how_to_add_it(
    find: Callable[[], object], refusal: str
) -> None:
    with pytest.raises(AuthError) as raised:
        find()

    assert str(raised.value) == refusal


def test_requiring_a_sign_in_returns_the_matching_one() -> None:
    save_jira(make_jira_credentials())
    save_notion(make_notion_credentials())

    assert (require_jira("example.atlassian.net"), require_notion("workspace-id")) == (
        SignIn(make_jira_credentials(), "keychain"),
        SignIn(make_notion_credentials(), "keychain"),
    )


def test_a_legacy_jira_entry_is_read_and_moved_to_its_site_key(keychain: InMemoryKeyring) -> None:
    keychain.entries[("skaldr", "jira")] = make_jira_credentials().model_dump_json()

    assert load_jira() == SignIn(make_jira_credentials(), "keychain")
    assert keychain.entries == {
        ("skaldr", "jira:https://example.atlassian.net"): make_jira_credentials().model_dump_json(),
        ("skaldr", "index"): index_of(jira=["jira:https://example.atlassian.net"]),
    }


def test_a_legacy_notion_entry_is_read_and_moved_to_the_unidentified_workspace_key(
    keychain: InMemoryKeyring,
) -> None:
    legacy = make_notion_credentials(workspace_id=None)
    keychain.entries[("skaldr", "notion")] = legacy_entry_json(legacy)

    assert load_notion() == SignIn(legacy, "keychain")
    assert keychain.entries == {
        ("skaldr", "notion:unidentified"): legacy.model_dump_json(),
        ("skaldr", "index"): index_of(notion=["notion:unidentified"]),
    }


def test_a_legacy_entry_is_moved_before_a_second_sign_in_is_written(keychain: InMemoryKeyring) -> None:
    other = make_jira_credentials(site="https://other.atlassian.net")
    keychain.entries[("skaldr", "jira")] = make_jira_credentials().model_dump_json()

    save_jira(other)

    assert keychain.entries == {
        ("skaldr", "jira:https://example.atlassian.net"): make_jira_credentials().model_dump_json(),
        ("skaldr", "jira:https://other.atlassian.net"): other.model_dump_json(),
        ("skaldr", "index"): index_of(
            jira=["jira:https://example.atlassian.net", "jira:https://other.atlassian.net"]
        ),
    }


def test_a_legacy_entry_for_a_site_that_is_already_keyed_gives_way_to_the_keyed_one(
    keychain: InMemoryKeyring,
) -> None:
    save_jira(make_jira_credentials(api_token="keyed-token"))
    keychain.entries[("skaldr", "jira")] = make_jira_credentials(api_token="legacy-token").model_dump_json()

    assert load_jira() == SignIn(make_jira_credentials(api_token="keyed-token"), "keychain")
    assert ("skaldr", "jira") not in keychain.entries


def test_an_unreadable_legacy_entry_stays_where_it_is_and_is_listed_as_unreadable(
    keychain: InMemoryKeyring,
) -> None:
    keychain.entries[("skaldr", "jira")] = "not json"

    assert stored_jira_sign_ins() == [StoredEntry("jira", "jira", None)]
    assert keychain.entries == {("skaldr", "jira"): "not json"}


def test_a_keyed_entry_that_cannot_be_read_names_its_site(keychain: InMemoryKeyring) -> None:
    keychain.entries[("skaldr", "jira:https://example.atlassian.net")] = "not json"
    keychain.entries[("skaldr", "index")] = index_of(jira=["jira:https://example.atlassian.net"])

    with pytest.raises(AuthError) as raised:
        load_jira()

    assert str(raised.value) == (
        "The keychain entry for jira https://example.atlassian.net is unreadable; "
        "run `skaldr auth jira` again"
    )


def test_an_unreadable_index_is_reported_and_leaves_the_keychain_alone(keychain: InMemoryKeyring) -> None:
    keychain.entries[("skaldr", "index")] = "not json"

    with pytest.raises(AuthError) as raised:
        load_jira()

    assert (str(raised.value), keychain.entries) == (
        "The keychain index that lists the skaldr sign-ins is unreadable; remove the keychain entry "
        "named index under skaldr and run `skaldr auth` again for each sign-in",
        {("skaldr", "index"): "not json"},
    )


def test_a_notion_sign_in_is_replaced_by_the_workspace_it_names_and_the_unidentified_one_by_name(
    keychain: InMemoryKeyring,
) -> None:
    legacy = make_notion_credentials(workspace_id=None, access_token="legacy-access")
    other = make_notion_credentials(workspace_id="other-id", workspace_name="Other Workspace")
    keychain.entries[("skaldr", "notion")] = legacy_entry_json(legacy)
    save_notion(other)

    assert (
        stored_notion_replaced_by(make_notion_credentials()),
        stored_notion_replaced_by(make_notion_credentials(workspace_id="other-id")),
        stored_notion_replaced_by(make_notion_credentials(workspace_id="new-id", workspace_name="Nowhere")),
    ) == (
        StoredEntry("notion", "notion:unidentified", legacy),
        StoredEntry("notion", "notion:other-id", other),
        None,
    )


def test_forgetting_a_sign_in_deletes_its_entry_and_leaves_the_others(keychain: InMemoryKeyring) -> None:
    other = make_jira_credentials(site="https://other.atlassian.net")
    save_jira(make_jira_credentials())
    save_jira(other)
    [first, _] = stored_jira_sign_ins()

    forget(first)

    assert stored_jira_sign_ins() == [StoredEntry("jira", "jira:https://other.atlassian.net", other)]
    assert keychain.entries[("skaldr", "index")] == index_of(jira=["jira:https://other.atlassian.net"])


def test_forgetting_an_entry_that_is_already_gone_is_not_an_error(keychain: InMemoryKeyring) -> None:
    save_jira(make_jira_credentials())
    [entry] = stored_jira_sign_ins()

    forget(entry)
    forget(entry)

    assert keychain.entries == {("skaldr", "index"): index_of()}


def test_nothing_saved_loads_as_signed_out() -> None:
    assert (load_notion(), load_jira()) == (None, None)


def test_a_notion_access_token_in_the_environment_wins_over_the_keychain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_notion(make_notion_credentials())
    monkeypatch.setenv("NOTION_ACCESS_TOKEN", "env-access")
    monkeypatch.setenv("NOTION_CLIENT_ID", "env-client")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "env-secret")

    assert load_notion() == SignIn(
        NotionCredentials(
            client_id="env-client",
            client_secret="env-secret",
            access_token="env-access",
            refresh_token=None,
            workspace_name=None,
        ),
        "environment",
    )


def test_blank_notion_variables_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTION_ACCESS_TOKEN", " env-access ")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "")
    monkeypatch.setenv("NOTION_CLIENT_ID", "   ")

    assert load_notion() == SignIn(
        NotionCredentials(
            client_id=None,
            client_secret=None,
            access_token="env-access",
            refresh_token=None,
            workspace_name=None,
        ),
        "environment",
    )


@pytest.mark.parametrize(
    ("variables", "missing"),
    [
        ({"NOTION_CLIENT_ID": "env-client"}, "NOTION_CLIENT_SECRET"),
        ({"NOTION_CLIENT_ID": " ", "NOTION_CLIENT_SECRET": "env-secret"}, "NOTION_CLIENT_ID"),
    ],
    ids=["only the client id", "a blank client id"],
)
def test_a_notion_access_token_with_half_a_client_names_the_missing_variable(
    monkeypatch: pytest.MonkeyPatch, variables: dict[str, str], missing: str
) -> None:
    monkeypatch.setenv("NOTION_ACCESS_TOKEN", "env-access")
    for name, value in variables.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(AuthError) as raised:
        load_notion()

    assert str(raised.value) == f"NOTION_CLIENT_ID, NOTION_CLIENT_SECRET go together; missing {missing}"


def test_a_blank_notion_access_token_falls_back_to_the_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    save_notion(make_notion_credentials())
    monkeypatch.setenv("NOTION_ACCESS_TOKEN", "  ")
    monkeypatch.setenv("NOTION_CLIENT_ID", "env-client")

    assert load_notion() == SignIn(make_notion_credentials(), "keychain")


def test_a_complete_jira_environment_wins_over_the_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    save_jira(make_jira_credentials())
    monkeypatch.setenv("JIRA_SITE", "other.atlassian.net/jira/your-work")
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


@pytest.mark.parametrize(
    ("variables", "missing"),
    [
        ({"JIRA_EMAIL": "ci@example.com"}, "JIRA_SITE, JIRA_API_TOKEN"),
        (
            {
                "JIRA_SITE": "https://example.atlassian.net",
                "JIRA_EMAIL": "ci@example.com",
                "JIRA_API_TOKEN": " ",
            },
            "JIRA_API_TOKEN",
        ),
    ],
    ids=["only the email", "a blank token"],
)
def test_a_partial_jira_environment_names_the_missing_variables(
    monkeypatch: pytest.MonkeyPatch, variables: dict[str, str], missing: str
) -> None:
    for name, value in variables.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(
        AuthError, match=rf"^JIRA_SITE, JIRA_EMAIL, JIRA_API_TOKEN go together; missing {missing}$"
    ):
        load_jira()


def test_a_jira_site_in_the_environment_must_be_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_SITE", "http://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "ci@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "env-token")

    with pytest.raises(AuthError, match=r"^JIRA_SITE: The Jira site must be an https URL"):
        load_jira()


@pytest.mark.parametrize(
    "stored",
    [
        "not json",
        '{"site": "http://example.atlassian.net", "email": "e", "api_token": "t", "display_name": null}',
    ],
    ids=["not json", "an http site"],
)
def test_an_unreadable_keychain_entry_says_to_sign_in_again(keychain: InMemoryKeyring, stored: str) -> None:
    keychain.entries[("skaldr", "jira")] = stored

    with pytest.raises(
        AuthError, match=r"^The keychain entry for jira is unreadable; run `skaldr auth jira` again$"
    ):
        load_jira()


@pytest.mark.parametrize(
    ("service", "stored", "load"),
    [
        ("notion", '{"access_token": "secret-access-value"}', load_notion),
        ("jira", '{"email": "e", "display_name": null, "api_token": "secret-access-value"}', load_jira),
    ],
    ids=["notion missing fields", "jira missing its site"],
)
def test_an_unreadable_keychain_entry_keeps_its_secret_out_of_the_traceback(
    keychain: InMemoryKeyring, service: str, stored: str, load: Callable[[], object]
) -> None:
    keychain.entries[("skaldr", service)] = stored

    with pytest.raises(AuthError) as raised:
        load()

    assert_secret_not_in_error_chain(raised.value, "secret-access-value")


def test_a_refused_site_keeps_its_password_out_of_the_traceback() -> None:
    with pytest.raises(AuthError) as raised:
        jira_credentials(SITE_WITH_A_PASSWORD, "e", "api-token")

    assert_secret_not_in_error_chain(raised.value, "secret-password")


def test_a_refused_jira_site_in_the_environment_keeps_its_password_out_of_the_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_SITE", SITE_WITH_A_PASSWORD)
    monkeypatch.setenv("JIRA_EMAIL", "ci@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "env-token")

    with pytest.raises(AuthError) as raised:
        load_jira()

    assert_secret_not_in_error_chain(raised.value, "secret-password")


@pytest.mark.parametrize(
    "operation",
    [
        lambda: save_notion(make_notion_credentials()),
        load_jira,
        lambda: forget(AN_ENTRY),
        refuse_an_unusable_keychain,
    ],
    ids=["save", "load", "forget", "the check before sign-in"],
)
def test_a_locked_keychain_is_reported(operation: Callable[[], object]) -> None:
    keyring.set_keyring(LockedKeyring())

    with pytest.raises(AuthError, match=r"^The system keychain is unavailable: locked$"):
        operation()


def test_a_slow_keychain_says_what_skaldr_is_waiting_for_and_then_answers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(store, "KEYCHAIN_NOTICE_SECONDS", 0.05)
    slow = SlowKeyring(answers_after=0.5)
    slow.entries[("skaldr", "jira")] = make_jira_credentials().model_dump_json()
    keyring.set_keyring(slow)

    loaded = load_jira()

    assert loaded == SignIn(make_jira_credentials(), "keychain")
    assert capsys.readouterr().err == WAITING_FOR_THE_KEYCHAIN


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda: save_notion(make_notion_credentials()), id="save"),
        pytest.param(load_jira, id="load"),
        pytest.param(lambda: forget(AN_ENTRY), id="forget"),
        pytest.param(refuse_an_unusable_keychain, id="the check before sign-in"),
    ],
)
def test_a_keychain_that_never_answers_stops_with_an_error_after_one_notice(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], operation: Callable[[], object]
) -> None:
    monkeypatch.setattr(store, "KEYCHAIN_NOTICE_SECONDS", 0.05)
    monkeypatch.setattr(store, "KEYCHAIN_TIMEOUT_SECONDS", 0.2)
    slow = SlowKeyring(answers_after=30)
    keyring.set_keyring(slow)
    started = time.monotonic()

    try:
        with pytest.raises(AuthError, match=r"^The system keychain did not answer within 0\.2 seconds"):
            operation()
    finally:
        slow.released.set()

    assert time.monotonic() - started < 2
    assert capsys.readouterr().err == WAITING_FOR_THE_KEYCHAIN


@pytest.mark.usefixtures("keychain")
def test_a_prompt_keychain_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    save_notion(make_notion_credentials())
    load_notion()

    assert capsys.readouterr().err == ""


INSECURE_BACKENDS = [
    pytest.param(PlaintextKeyring, "keyrings.alt.file.PlaintextKeyring", id="keyrings.alt plaintext"),
    pytest.param(null.Keyring, "keyring.backends.null.Keyring", id="null"),
    pytest.param(fail.Keyring, "keyring.backends.fail.Keyring", id="fail"),
    pytest.param(
        PlaintextKeyringSubclass,
        "tests.factories.auth_factory.PlaintextKeyringSubclass (a keyrings.alt.file.PlaintextKeyring)",
        id="a subclass of a keyrings.alt backend",
    ),
    pytest.param(
        NullKeyringSubclass,
        "tests.factories.auth_factory.NullKeyringSubclass (a keyring.backends.null.Keyring)",
        id="a subclass of the null backend",
    ),
]


@pytest.mark.parametrize(("backend_class", "backend_name"), INSECURE_BACKENDS)
def test_saving_to_an_insecure_keyring_backend_is_refused_by_name(
    backend_class: type[KeyringBackend], backend_name: str
) -> None:
    keyring.set_keyring(backend_class())

    with pytest.raises(AuthError) as raised:
        save_jira(make_jira_credentials())

    assert str(raised.value) == insecure_keyring_refusal(backend_name)


@pytest.mark.parametrize(("backend_class", "backend_name"), INSECURE_BACKENDS)
def test_the_keychain_check_before_sign_in_refuses_an_insecure_backend_by_name(
    backend_class: type[KeyringBackend], backend_name: str
) -> None:
    keyring.set_keyring(backend_class())

    with pytest.raises(AuthError) as raised:
        refuse_an_unusable_keychain()

    assert str(raised.value) == insecure_keyring_refusal(backend_name)


def test_the_keychain_check_before_sign_in_passes_a_working_keychain_and_changes_nothing(
    keychain: InMemoryKeyring,
) -> None:
    save_jira(make_jira_credentials())

    entries_before = dict(keychain.entries)

    refuse_an_unusable_keychain()

    assert keychain.entries == entries_before


def test_the_keychain_check_before_sign_in_reads_exactly_the_index_entry() -> None:
    recording = ReadRecordingKeyring()
    keyring.set_keyring(recording)

    refuse_an_unusable_keychain()

    assert recording.reads == [("skaldr", "index")]


def test_a_refused_plaintext_keyring_receives_nothing() -> None:
    plaintext = PlaintextKeyring()
    keyring.set_keyring(plaintext)

    with pytest.raises(AuthError) as raised:
        save_notion(make_notion_credentials())

    assert (str(raised.value), plaintext.entries) == (
        insecure_keyring_refusal("keyrings.alt.file.PlaintextKeyring"),
        {},
    )


def test_a_chained_keyring_with_an_insecure_backend_in_it_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    secure, plaintext = InMemoryKeyring(), PlaintextKeyring()
    monkeypatch.setattr(ChainerBackend, "backends", [secure, plaintext])
    keyring.set_keyring(ChainerBackend())

    with pytest.raises(AuthError) as raised:
        save_jira(make_jira_credentials())

    assert (str(raised.value), secure.entries, plaintext.entries) == (
        insecure_keyring_refusal("keyrings.alt.file.PlaintextKeyring"),
        {},
        {},
    )


def test_a_chained_keyring_of_secure_backends_is_saved_to(monkeypatch: pytest.MonkeyPatch) -> None:
    secure = InMemoryKeyring()
    monkeypatch.setattr(ChainerBackend, "backends", [secure])
    keyring.set_keyring(ChainerBackend())

    save_jira(make_jira_credentials())

    assert secure.entries == {
        ("skaldr", "jira:https://example.atlassian.net"): make_jira_credentials().model_dump_json(),
        ("skaldr", "index"): index_of(jira=["jira:https://example.atlassian.net"]),
    }


@pytest.mark.parametrize(
    ("typed", "site"),
    [
        ("example.atlassian.net", "https://example.atlassian.net"),
        ("https://Example.atlassian.net/", "https://example.atlassian.net"),
        ("  https://example.atlassian.net/jira/your-work  ", "https://example.atlassian.net"),
        ("https://example.atlassian.net:443", "https://example.atlassian.net"),
        ("https://example.atlassian.net:8443", "https://example.atlassian.net:8443"),
    ],
    ids=["bare host", "trailing slash", "a page url", "the default port", "another port"],
)
def test_a_typed_site_becomes_its_https_origin(typed: str, site: str) -> None:
    assert normalise_site(typed) == site


@pytest.mark.parametrize(
    "typed",
    [
        "http://example.atlassian.net",
        "",
        "https://",
        "https://example.atlassian.net:abc",
        "https://example.atlassian.net:99999",
    ],
    ids=["http", "empty", "no host", "a word for a port", "a port out of range"],
)
def test_a_site_that_is_not_an_https_origin_is_refused(typed: str) -> None:
    with pytest.raises(AuthError, match=r"^The Jira site must be an https URL"):
        normalise_site(typed)


@pytest.mark.parametrize(("typed", "refusal"), SITE_REFUSALS)
def test_a_site_that_is_not_a_plain_jira_cloud_origin_is_refused(typed: str, refusal: str) -> None:
    with pytest.raises(AuthError) as raised:
        normalise_site(typed)

    assert str(raised.value) == refusal


@pytest.mark.parametrize("typed", SITES_OFF_JIRA_CLOUD)
def test_a_keychain_entry_for_a_site_off_jira_cloud_is_unreadable(
    keychain: InMemoryKeyring, typed: str
) -> None:
    keychain.entries[("skaldr", "jira")] = json.dumps({**make_jira_credentials().model_dump(), "site": typed})

    with pytest.raises(
        AuthError, match=r"^The keychain entry for jira is unreadable; run `skaldr auth jira` again$"
    ):
        load_jira()


@pytest.mark.parametrize(("typed", "refusal"), SITE_REFUSALS)
def test_a_jira_site_in_the_environment_off_jira_cloud_is_refused(
    monkeypatch: pytest.MonkeyPatch, typed: str, refusal: str
) -> None:
    monkeypatch.setenv("JIRA_SITE", typed)
    monkeypatch.setenv("JIRA_EMAIL", "ci@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "env-token")

    with pytest.raises(AuthError) as raised:
        load_jira()

    assert str(raised.value) == f"JIRA_SITE: {refusal}"


def test_jira_credentials_hold_only_an_https_origin() -> None:
    with pytest.raises(ValidationError, match="The Jira site must be an https URL"):
        make_jira_credentials(site="http://example.atlassian.net")


def test_jira_credentials_built_from_typed_values_refuse_a_bad_site_by_name() -> None:
    with pytest.raises(
        AuthError,
        match=r"^The Jira site must be an https URL like https://<site>\.atlassian\.net, not 'ftp://\{x\}'$",
    ):
        jira_credentials("ftp://{x}", "reader@example.com", "api-token")


def test_jira_credentials_built_from_typed_values_normalise_the_site() -> None:
    assert jira_credentials("Example.atlassian.net/", "reader@example.com", "api-token") == (
        make_jira_credentials(display_name=None)
    )
