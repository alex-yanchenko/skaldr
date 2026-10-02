import json
import traceback
from collections.abc import Callable

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail, null
from keyring.backends.chainer import ChainerBackend
from pydantic import ValidationError

from skaldr.auth.store import (
    JiraCredentials,
    NotionCredentials,
    SignIn,
    forget,
    jira_credentials,
    load_jira,
    load_notion,
    normalise_site,
    save_jira,
    save_notion,
)
from skaldr.errors import AuthError
from tests.factories.auth_factory import (
    SITE_REFUSALS,
    SITES_OFF_JIRA_CLOUD,
    InMemoryKeyring,
    LockedKeyring,
    PlaintextKeyring,
    make_jira_credentials,
    make_notion_credentials,
)


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

    assert "secret-access-value" not in "".join(traceback.format_exception(raised.value))


SITE_WITH_A_PASSWORD = "https://reader:secret-password@example.atlassian.net"


def test_a_refused_site_keeps_its_password_out_of_the_traceback() -> None:
    with pytest.raises(AuthError) as raised:
        jira_credentials(SITE_WITH_A_PASSWORD, "e", "api-token")

    assert "secret-password" not in "".join(traceback.format_exception(raised.value))


def test_a_refused_jira_site_in_the_environment_keeps_its_password_out_of_the_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_SITE", SITE_WITH_A_PASSWORD)
    monkeypatch.setenv("JIRA_EMAIL", "ci@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "env-token")

    with pytest.raises(AuthError) as raised:
        load_jira()

    assert "secret-password" not in "".join(traceback.format_exception(raised.value))


def test_forget_deletes_the_entry_and_reports_whether_one_existed(keychain: InMemoryKeyring) -> None:
    save_jira(make_jira_credentials())

    assert (forget("jira"), forget("jira")) == (True, False)
    assert keychain.entries == {}


@pytest.mark.parametrize(
    "operation",
    [lambda: save_notion(make_notion_credentials()), load_jira, lambda: forget("jira")],
    ids=["save", "load", "forget"],
)
def test_a_locked_keychain_is_reported(operation: Callable[[], object]) -> None:
    keyring.set_keyring(LockedKeyring())

    with pytest.raises(AuthError, match=r"^The system keychain is unavailable: locked$"):
        operation()


def insecure_keyring_refusal(backend: str) -> str:
    return (
        f"The keyring backend {backend} does not keep secrets in a secure store, so skaldr will not save to "
        "it. Choose a secure backend with the PYTHON_KEYRING_BACKEND environment variable or keyring's "
        "keyringrc.cfg, for example keyring.backends.macOS.Keyring, keyring.backends.Windows.WinVaultKeyring "
        "or keyring.backends.SecretService.Keyring"
    )


@pytest.mark.parametrize(
    ("backend", "name"),
    [
        (PlaintextKeyring(), "keyrings.alt.file.PlaintextKeyring"),
        (null.Keyring(), "keyring.backends.null.Keyring"),
        (fail.Keyring(), "keyring.backends.fail.Keyring"),
    ],
    ids=["keyrings.alt plaintext", "null", "fail"],
)
def test_saving_to_an_insecure_keyring_backend_is_refused_by_name(backend: KeyringBackend, name: str) -> None:
    keyring.set_keyring(backend)

    with pytest.raises(AuthError) as raised:
        save_jira(make_jira_credentials())

    assert str(raised.value) == insecure_keyring_refusal(name)


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

    assert secure.entries == {("skaldr", "jira"): make_jira_credentials().model_dump_json()}


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
