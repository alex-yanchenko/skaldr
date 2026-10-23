import json
import os
import subprocess
import sys
from pathlib import Path

import keyring
import pytest
from keyring.backends import null

from skaldr.auth import store, templates
from tests.conftest import REPO_ROOT
from tests.factories import auth_factory
from tests.factories.auth_factory import (
    WORKSPACE_ID,
    InMemoryKeyring,
    PlaintextKeyring,
    UnsafeTestHelperCallError,
    make_notion_credentials,
    refuse_outside_the_tests_setup,
    seed_notion,
)

RUN_THROUGH_PYTEST = "run the tests through pytest so"
NULL_BACKEND_REFUSAL = (
    "seed_notion refused: the keyring backend is keyring.backends.null.Keyring, not an InMemoryKeyring; "
    f"{RUN_THROUGH_PYTEST} tests/conftest.py installs one"
)


def test_the_guard_stops_seeding_when_the_keyring_is_not_in_memory(tmp_path: Path) -> None:
    keyring.set_keyring(null.Keyring())

    with pytest.raises(UnsafeTestHelperCallError) as refusal:
        seed_notion(make_notion_credentials())

    assert (str(refusal.value), sorted(path.name for path in tmp_path.iterdir())) == (
        NULL_BACKEND_REFUSAL,
        [],
    )


def test_the_guard_stops_seeding_when_the_auth_lock_is_still_in_the_real_state_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, keychain: InMemoryKeyring
) -> None:
    stand_in_for_the_real_lock = tmp_path / "real-auth.lock"
    monkeypatch.setattr(store, "lock_file", lambda: stand_in_for_the_real_lock)
    monkeypatch.setattr(auth_factory, "REAL_LOCK_FILE", store.lock_file)

    with pytest.raises(UnsafeTestHelperCallError) as refusal:
        seed_notion(make_notion_credentials())

    assert (str(refusal.value), sorted(path.name for path in tmp_path.iterdir()), keychain.entries) == (
        "seed_notion refused: skaldr.auth.store.lock_file still points at skaldr's real state directory; "
        f"{RUN_THROUGH_PYTEST} tests/conftest.py redirects it",
        [],
        {},
    )


def test_the_guard_stops_a_helper_when_the_notion_templates_file_is_still_in_the_real_state_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_factory, "REAL_TEMPLATE_FILE", templates.template_file)

    with pytest.raises(UnsafeTestHelperCallError) as refusal:
        refuse_outside_the_tests_setup("a_template_helper")

    assert str(refusal.value) == (
        "a_template_helper refused: skaldr.auth.templates.template_file still points at skaldr's real state "
        f"directory; {RUN_THROUGH_PYTEST} tests/conftest.py redirects it"
    )


def test_the_guard_lets_seeding_through_under_the_normal_fixtures(keychain: InMemoryKeyring) -> None:
    seed_notion(make_notion_credentials())

    assert (sorted(keychain.entries), json.loads(keychain.entries[("skaldr", "index")])) == (
        [("skaldr", "index"), ("skaldr", f"notion:{WORKSPACE_ID}")],
        {"jira": [], "notion": [f"notion:{WORKSPACE_ID}"]},
    )


def test_the_guard_accepts_a_subclass_of_the_in_memory_keyring() -> None:
    keyring.set_keyring(PlaintextKeyring())

    refuse_outside_the_tests_setup("a_helper")


def test_the_guard_stops_a_script_that_seeds_a_sign_in_without_the_tests_setup(tmp_path: Path) -> None:
    script = "\n".join(
        [
            "from tests.factories.auth_factory import make_notion_credentials, seed_notion",
            "seed_notion(make_notion_credentials())",
        ]
    )
    environment = {
        **os.environ,
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "XDG_STATE_HOME": str(tmp_path),
    }

    finished = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env=environment,
    )

    assert (
        finished.returncode,
        finished.stdout,
        finished.stderr.splitlines()[-1],
        sorted(path.name for path in tmp_path.iterdir()),
    ) == (
        1,
        "",
        "tests.factories.auth_factory.UnsafeTestHelperCallError: " + NULL_BACKEND_REFUSAL,
        [],
    )
