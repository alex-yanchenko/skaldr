import threading
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest

from skaldr.auth.notion import CALLBACK_THREAD_PREFIX
from skaldr.auth.store import JIRA_ENVIRONMENT, NOTION_ENVIRONMENT
from tests.factories.auth_factory import InMemoryKeyring

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


@pytest.fixture(autouse=True)
def no_callback_server_outlives_its_test() -> Iterator[None]:
    yield
    serving = [thread for thread in threading.enumerate() if thread.name.startswith(CALLBACK_THREAD_PREFIX)]
    for thread in serving:
        thread.join(timeout=2)
    assert [thread.name for thread in serving if thread.is_alive()] == []


@pytest.fixture(autouse=True)
def _disable_skill_sync(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """`main()` runs an opportunistic skill sync against the real `~/.claude` on every invocation.
    Disable it by default so a test that drives `main()` never reads or rewrites the developer's own
    installed skills. The sync's own tests re-enable it (via `monkeypatch.delenv`) and drive it against
    a tmp home explicitly."""
    monkeypatch.setenv("SKALDR_SKILL_SYNC", "0")
