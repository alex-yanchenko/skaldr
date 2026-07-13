"""Optional PDF output: drive a headless Chrome/Chromium/Edge to print the HTML to a PDF.

skaldr's print CSS makes a report paginate cleanly, but only a browser applies it — and printing a
published Artifact doesn't work (it's a sandboxed cross-origin frame the browser flattens to a
snapshot). Rather than ask the reader to render HTML and print by hand, `--pdf` shells out to a
browser they already have. No new Python dependency; if no browser is found we say so and leave the
HTML path untouched.
"""

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from skaldr.errors import ReportError

# A hang shouldn't wedge the CLI forever; a module constant so tests can shorten it.
_TIMEOUT_SECONDS = 120

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


def _is_executable(path: str) -> bool:
    """A runnable browser binary — a regular file with the executable bit (not a dir or data file)."""
    candidate = Path(path)
    return candidate.is_file() and os.access(candidate, os.X_OK)


def find_browser() -> str | None:
    """Path to a Chromium-family browser to print with, or None if none is installed. `SKALDR_BROWSER`
    wins if set; a set-but-unrunnable override raises rather than silently falling back to discovery,
    so a typo'd path fails loudly instead of masquerading as 'no browser installed'."""
    override = os.environ.get("SKALDR_BROWSER")
    if override:
        if _is_executable(override):
            return override
        raise ReportError(
            f"SKALDR_BROWSER is set to {override!r}, but that is not a runnable browser (no such "
            "executable file). Fix the path, or unset SKALDR_BROWSER to auto-discover one."
        )
    for binary in _MAC_APP_BINARIES:
        if _is_executable(binary):
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
        # start_new_session puts the browser in its own process group so a timeout can kill the
        # headless renderer/GPU children too, not just the launcher (which would orphan them).
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
            )
        except OSError as err:
            raise ReportError(f"could not run the browser for --pdf ({binary}): {err}") from err
        try:
            _, stderr = process.communicate(timeout=_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as err:
            _kill_process_group(process)
            raise ReportError(
                f"the browser timed out after {_TIMEOUT_SECONDS}s rendering the PDF ({binary})"
            ) from err
        returncode = process.returncode
    if returncode != 0 or not pdf_path.exists():
        detail = stderr.strip().splitlines()[-1] if stderr.strip() else "no output"
        raise ReportError(f"the browser failed to produce a PDF (exit {returncode}): {detail}")


def _kill_process_group(process: "subprocess.Popen[str]") -> None:
    """SIGKILL the whole process group (POSIX) or the process (elsewhere), then reap it."""
    with contextlib.suppress(OSError, ProcessLookupError):
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        process.communicate(timeout=5)
