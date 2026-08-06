from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _disable_skill_sync(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """`main()` runs an opportunistic skill sync against the real `~/.claude` on every invocation.
    Disable it by default so a test that drives `main()` never reads or rewrites the developer's own
    installed skills. The sync's own tests re-enable it (via `monkeypatch.delenv`) and drive it against
    a tmp home explicitly."""
    monkeypatch.setenv("SKALDR_SKILL_SYNC", "0")
