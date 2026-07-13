"""Optional PDF output: drive a headless Chrome/Chromium/Edge to print the HTML to a PDF.

skaldr's print CSS makes a report paginate cleanly, but only a browser applies it — and printing a
published Artifact doesn't work (it's a sandboxed cross-origin frame the browser flattens to a
snapshot). Rather than ask the reader to render HTML and print by hand, `--pdf` shells out to a
browser they already have. No new Python dependency; if no browser is found we say so and leave the
HTML path untouched.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from skaldr.errors import ReportError

# macOS .app binaries, tried in order; then PATH names. SKALDR_BROWSER overrides everything.
_MAC_APP_BINARIES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
_PATH_NAMES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
    "microsoft-edge",
)


def find_browser() -> str | None:
    """Path to a Chromium-family browser to print with, or None. `SKALDR_BROWSER` wins if set."""
    override = os.environ.get("SKALDR_BROWSER")
    if override:
        return override if Path(override).exists() else None
    for binary in _MAC_APP_BINARIES:
        if Path(binary).exists():
            return binary
    for name in _PATH_NAMES:
        found = shutil.which(name)
        if found is not None:
            return found
    return None


def html_to_pdf(html: str, pdf_path: Path, *, browser: str | None = None) -> None:
    """Print `html` to `pdf_path` via a headless browser. Raises ReportError if none is available or
    the browser fails. `browser` overrides discovery (used by tests)."""
    binary = browser or find_browser()
    if binary is None:
        raise ReportError(
            "no Chrome/Chromium/Edge found to render a PDF. Install one, set SKALDR_BROWSER to its "
            "path, or drop --pdf and print the HTML from a browser."
        )
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="skaldr-pdf-") as tmp:
        work = Path(tmp)
        source = work / "page.html"
        source.write_text(html, encoding="utf-8")
        command = [
            binary,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",  # drop the browser's date/URL/page-number chrome
            f"--print-to-pdf={pdf_path}",
            source.as_uri(),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired) as err:
            raise ReportError(f"could not run the browser for --pdf ({binary}): {err}") from err
    if result.returncode != 0 or not pdf_path.exists():
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no output"
        raise ReportError(f"the browser failed to produce a PDF (exit {result.returncode}): {detail}")
