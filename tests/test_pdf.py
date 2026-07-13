from pathlib import Path

import pytest

from skaldr import pdf
from skaldr.errors import ReportError


def test_find_browser_honors_the_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "chrome"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("SKALDR_BROWSER", str(fake))

    assert pdf.find_browser() == str(fake)


def test_find_browser_env_override_that_does_not_exist_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An explicit-but-wrong override fails loudly rather than silently falling back to discovery.
    monkeypatch.setenv("SKALDR_BROWSER", str(tmp_path / "missing"))

    assert pdf.find_browser() is None


def test_html_to_pdf_without_a_browser_raises_a_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pdf, "find_browser", lambda: None)

    with pytest.raises(ReportError, match=r"no Chrome/Chromium/Edge found"):
        pdf.html_to_pdf("<html></html>", tmp_path / "out.pdf")


def test_html_to_pdf_surfaces_a_browser_failure(tmp_path: Path) -> None:
    # A stand-in "browser" that exits non-zero must surface as a clean ReportError, not a traceback.
    fake = tmp_path / "fake-browser"
    fake.write_text('#!/bin/sh\necho "boom" >&2\nexit 3\n', encoding="utf-8")
    fake.chmod(0o755)

    with pytest.raises(ReportError, match=r"browser failed to produce a PDF"):
        pdf.html_to_pdf("<html></html>", tmp_path / "out.pdf", browser=str(fake))
