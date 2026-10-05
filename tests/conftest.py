import threading
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest

from skaldr.auth.notion import CALLBACK_THREAD_PREFIX
from skaldr.auth.store import JIRA_ENVIRONMENT, NOTION_ENVIRONMENT
from tests.factories.auth_factory import InMemoryKeyring, PlaintextKeyring

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def keychain(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryKeyring]:
    for name in (*NOTION_ENVIRONMENT, *JIRA_ENVIRONMENT):
        monkeypatch.delenv(name, raising=False)
    previous = keyring.get_keyring()
    in_memory = InMemoryKeyring()
    keyring.set_keyring(in_memory)
    yield in_memory
    keyring.set_keyring(previous)


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
