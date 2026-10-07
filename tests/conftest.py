import os

os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"

import threading
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest

from skaldr.auth import store
from skaldr.auth.notion import CALLBACK_THREAD_PREFIX
from skaldr.auth.store import JIRA_ENVIRONMENT, NOTION_ENVIRONMENT
from tests.factories.auth_factory import InMemoryKeyring, PlaintextKeyring

REPO_ROOT = Path(__file__).resolve().parent.parent
KEYCHAIN_THREAD_NAME = "skaldr-keychain"
KEYCHAIN_THREAD_JOIN_SECONDS = 10.0

keyring.set_keyring(InMemoryKeyring())


def _refuse_a_keyring_that_is_not_in_memory(when: str) -> None:
    backend = keyring.get_keyring()
    if not isinstance(backend, InMemoryKeyring):
        pytest.exit(f"{when}: the test session has {type(backend).__module__}.{type(backend).__qualname__}")


def _finish_keychain_threads() -> list[str]:
    running = [thread for thread in threading.enumerate() if thread.name == KEYCHAIN_THREAD_NAME]
    for thread in running:
        thread.join(timeout=KEYCHAIN_THREAD_JOIN_SECONDS)
    return [thread.name for thread in running if thread.is_alive()]


@pytest.fixture(autouse=True)
def keychain(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryKeyring]:
    for name in (*NOTION_ENVIRONMENT, *JIRA_ENVIRONMENT):
        monkeypatch.delenv(name, raising=False)
    _refuse_a_keyring_that_is_not_in_memory("before the test")
    in_memory = InMemoryKeyring()
    keyring.set_keyring(in_memory)
    yield in_memory
    unfinished = _finish_keychain_threads()
    keyring.set_keyring(InMemoryKeyring())
    assert unfinished == []


@pytest.fixture(autouse=True)
def auth_lock_in_the_test_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(store, "lock_file", lambda: tmp_path / "auth.lock")


@pytest.fixture
def plaintext_keyring() -> PlaintextKeyring:
    plaintext = PlaintextKeyring()
    keyring.set_keyring(plaintext)
    return plaintext


@pytest.fixture(autouse=True)
def no_callback_server_outlives_its_test() -> Iterator[None]:
    yield
    serving = [thread for thread in threading.enumerate() if thread.name.startswith(CALLBACK_THREAD_PREFIX)]
    for thread in serving:
        thread.join(timeout=2)
    assert [thread.name for thread in serving if thread.is_alive()] == []


@pytest.fixture(autouse=True)
def _no_skill_sync_touches_the_developers_own_claude_home(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SKALDR_SKILL_SYNC", "0")
