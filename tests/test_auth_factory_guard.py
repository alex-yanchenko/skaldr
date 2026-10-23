import json
from collections.abc import Callable, Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import null

from skaldr.auth import store, templates
from tests.factories import auth_factory
from tests.factories.auth_factory import (
    WORKSPACE_ID,
    InMemoryKeyring,
    LockedKeyring,
    PlaintextKeyring,
    UnsafeTestHelperCallError,
    make_notion_credentials,
    refuse_outside_the_tests_setup,
    seed_notion,
)

RUN_THROUGH_PYTEST = "run the tests through pytest from the repository root"


@pytest.fixture
def install_backend(keychain: InMemoryKeyring) -> Iterator[Callable[[KeyringBackend], None]]:
    yield keyring.set_keyring
    keyring.set_keyring(keychain)


def test_seeding_a_sign_in_refuses_when_the_keyring_is_the_null_backend(
    install_backend: Callable[[KeyringBackend], None], tmp_path: Path
) -> None:
    install_backend(null.Keyring())

    with pytest.raises(UnsafeTestHelperCallError) as refusal:
        seed_notion(make_notion_credentials())

    assert (str(refusal.value), sorted(path.name for path in tmp_path.iterdir())) == (
        "seed_notion refused: the keyring backend is keyring.backends.null.Keyring, not an InMemoryKeyring; "
        f"{RUN_THROUGH_PYTEST} so tests/conftest.py installs one",
        [],
    )


def test_seeding_a_sign_in_refuses_a_backend_that_would_reach_a_real_keychain(
    install_backend: Callable[[KeyringBackend], None], tmp_path: Path
) -> None:
    install_backend(LockedKeyring())

    with pytest.raises(UnsafeTestHelperCallError) as refusal:
        seed_notion(make_notion_credentials())

    assert (str(refusal.value), sorted(path.name for path in tmp_path.iterdir())) == (
        "seed_notion refused: the keyring backend is tests.factories.auth_factory.LockedKeyring, not an "
        f"InMemoryKeyring; {RUN_THROUGH_PYTEST} so tests/conftest.py installs one",
        [],
    )


def test_seeding_a_sign_in_refuses_when_the_auth_lock_is_still_in_the_real_state_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stand_in_for_the_real_lock = tmp_path / "real-auth.lock"
    monkeypatch.setattr(store, "lock_file", lambda: stand_in_for_the_real_lock)
    monkeypatch.setattr(auth_factory, "REAL_LOCK_FILE", store.lock_file)

    with pytest.raises(UnsafeTestHelperCallError) as refusal:
        seed_notion(make_notion_credentials())

    assert (str(refusal.value), sorted(path.name for path in tmp_path.iterdir())) == (
        "seed_notion refused: skaldr.auth.store.lock_file still points at skaldr's real state directory; "
        f"{RUN_THROUGH_PYTEST} so tests/conftest.py redirects it",
        [],
    )


def test_the_guard_refuses_when_the_notion_templates_file_is_still_in_the_real_state_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_factory, "REAL_TEMPLATE_FILE", templates.template_file)

    with pytest.raises(UnsafeTestHelperCallError) as refusal:
        refuse_outside_the_tests_setup("a_template_helper")

    assert str(refusal.value) == (
        "a_template_helper refused: skaldr.auth.templates.template_file still points at skaldr's real state "
        f"directory; {RUN_THROUGH_PYTEST} so tests/conftest.py redirects it"
    )


def test_the_guard_checks_the_backend_it_is_given_rather_than_the_installed_one() -> None:
    with pytest.raises(UnsafeTestHelperCallError) as refusal:
        refuse_outside_the_tests_setup("a_helper", null.Keyring())

    assert str(refusal.value) == (
        "a_helper refused: the keyring backend is keyring.backends.null.Keyring, not an InMemoryKeyring; "
        f"{RUN_THROUGH_PYTEST} so tests/conftest.py installs one"
    )


def test_seeding_a_sign_in_still_works_under_the_normal_fixtures(keychain: InMemoryKeyring) -> None:
    seed_notion(make_notion_credentials())

    assert (
        sorted(keychain.entries),
        json.loads(keychain.entries[("skaldr", "index")]),
    ) == (
        [("skaldr", "index"), ("skaldr", f"notion:{WORKSPACE_ID}")],
        {"jira": [], "notion": [f"notion:{WORKSPACE_ID}"]},
    )


def test_the_guard_accepts_a_subclass_of_the_in_memory_keyring(
    install_backend: Callable[[KeyringBackend], None],
) -> None:
    install_backend(PlaintextKeyring())

    refuse_outside_the_tests_setup("a_helper")
