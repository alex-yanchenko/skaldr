import errno
import os
import stat
from pathlib import Path

import pytest

from skaldr import pdf
from skaldr.errors import ReadOnlyFileError, ReportError


def _executable(path: Path, script: str = "#!/bin/sh\nexit 0\n") -> Path:
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def _browser_printing(path: Path, content: str, *, exit_code: int) -> Path:
    write_to_print_target = 'printf %s "$content" > "${a#--print-to-pdf=}"'
    return _executable(
        path,
        "#!/bin/sh\n"
        f"content={content}\n"
        f'for a in "$@"; do case "$a" in --print-to-pdf=*) {write_to_print_target};; esac; done\n'
        f"exit {exit_code}\n",
    )


def test_find_browser_honors_an_executable_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _executable(tmp_path / "chrome")
    monkeypatch.setenv("SKALDR_BROWSER", str(fake))

    assert pdf.find_browser() == str(fake)


def test_find_browser_rejects_a_non_executable_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "chrome"
    plain.write_text("", encoding="utf-8")  # exists, but no executable bit
    monkeypatch.setenv("SKALDR_BROWSER", str(plain))

    with pytest.raises(ReportError, match=r"SKALDR_BROWSER is set to .*not a runnable browser"):
        pdf.find_browser()


def test_find_browser_rejects_a_missing_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # An explicit-but-wrong override fails loudly rather than silently falling back to discovery.
    monkeypatch.setenv("SKALDR_BROWSER", str(tmp_path / "missing"))

    with pytest.raises(ReportError, match=r"SKALDR_BROWSER is set to"):
        pdf.find_browser()


def test_find_browser_discovers_a_mac_app_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKALDR_BROWSER", raising=False)
    wanted = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    monkeypatch.setattr(pdf, "_MAC_APP_BINARIES", (wanted,))

    def only_wanted(path: str) -> bool:
        return path == wanted

    monkeypatch.setattr(pdf, "_is_executable", only_wanted)

    assert pdf.find_browser() == wanted


def test_find_browser_falls_back_to_a_path_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKALDR_BROWSER", raising=False)

    def none_executable(_path: str) -> bool:  # no mac-app binary present
        return False

    def which(name: str) -> str | None:
        return "/usr/bin/chromium" if name == "chromium" else None

    monkeypatch.setattr(pdf, "_is_executable", none_executable)
    monkeypatch.setattr(pdf.shutil, "which", which)

    assert pdf.find_browser() == "/usr/bin/chromium"


def test_find_browser_returns_none_when_nothing_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKALDR_BROWSER", raising=False)

    def none_executable(_path: str) -> bool:
        return False

    def none_on_path(_name: str) -> str | None:
        return None

    monkeypatch.setattr(pdf, "_is_executable", none_executable)
    monkeypatch.setattr(pdf.shutil, "which", none_on_path)

    assert pdf.find_browser() is None


def test_html_to_pdf_without_a_browser_raises_a_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pdf, "find_browser", lambda: None)

    with pytest.raises(ReportError, match=r"no Chrome/Chromium/Edge found"):
        pdf.html_to_pdf("<html></html>", tmp_path / "out.pdf")


def test_html_to_pdf_runs_the_browser_with_the_expected_command(tmp_path: Path) -> None:
    argv_dump = tmp_path / "argv.txt"
    fake = _executable(
        tmp_path / "fake-browser",
        # Record argv, then create whatever file --print-to-pdf points at, mimicking a real print.
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{argv_dump}"\n'
        'for a in "$@"; do case "$a" in --print-to-pdf=*) : > "${a#--print-to-pdf=}";; esac; done\n'
        "exit 0\n",
    )
    out = tmp_path / "sub" / "out.pdf"

    pdf.html_to_pdf("<html>hi</html>", out, browser=str(fake))

    assert out.exists()  # parent dir was created and the PDF written
    # argv seen by the browser (its own path is argv[0], not captured by "$@")
    args = argv_dump.read_text(encoding="utf-8").splitlines()
    assert args[:3] == ["--headless", "--disable-gpu", "--no-pdf-header-footer"]
    assert args[3].startswith("--print-to-pdf=") and args[3].endswith("page.pdf")
    assert args[3] != f"--print-to-pdf={out}"
    assert args[4].startswith("file://") and args[4].endswith("page.html")


def test_html_to_pdf_leaves_an_earlier_pdf_alone_when_the_browser_fails_after_writing(
    tmp_path: Path,
) -> None:
    fake = _browser_printing(tmp_path / "fake-browser", "partial", exit_code=3)
    out = tmp_path / "out.pdf"
    out.write_bytes(b"earlier pdf")

    with pytest.raises(ReportError, match=r"browser failed to produce a PDF \(exit 3\): no output"):
        pdf.html_to_pdf("<html></html>", out, browser=str(fake))

    assert (out.read_bytes(), sorted(tmp_path.iterdir())) == (b"earlier pdf", [fake, out])


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes a read-only file")
def test_html_to_pdf_refuses_a_read_only_target_before_it_runs_the_browser(tmp_path: Path) -> None:
    ran = tmp_path / "browser-ran"
    fake = _executable(tmp_path / "fake-browser", f"#!/bin/sh\n: > {ran}\nexit 0\n")
    out = tmp_path / "out.pdf"
    out.write_bytes(b"earlier pdf")
    out.chmod(0o444)

    with pytest.raises(ReadOnlyFileError) as raised:
        pdf.html_to_pdf("<html></html>", out, browser=str(fake))

    assert (str(raised.value), ran.exists(), out.read_bytes()) == (
        f"[Errno {errno.EACCES}] the file is read-only, so skaldr leaves it as it is: '{out}'",
        False,
        b"earlier pdf",
    )


def test_html_to_pdf_writes_through_a_symlink_and_keeps_the_link(tmp_path: Path) -> None:
    fake = _browser_printing(tmp_path / "fake-browser", "new-pdf", exit_code=0)
    target = tmp_path / "published" / "out.pdf"
    target.parent.mkdir()
    target.write_bytes(b"earlier pdf")
    target.chmod(0o640)
    link = tmp_path / "out.pdf"
    link.symlink_to(target)

    pdf.html_to_pdf("<html></html>", link, browser=str(fake))

    assert (link.is_symlink(), target.read_bytes(), stat.S_IMODE(target.stat().st_mode)) == (
        True,
        b"new-pdf",
        0o640,
    )


def test_html_to_pdf_surfaces_a_nonzero_exit(tmp_path: Path) -> None:
    fake = _executable(tmp_path / "fake-browser", '#!/bin/sh\necho "boom" >&2\nexit 3\n')

    with pytest.raises(ReportError, match=r"browser failed to produce a PDF \(exit 3\): boom"):
        pdf.html_to_pdf("<html></html>", tmp_path / "out.pdf", browser=str(fake))


def test_html_to_pdf_reports_a_clean_exit_that_wrote_no_pdf(tmp_path: Path) -> None:
    # exit 0 but no file — a silently no-op browser must still surface as an error, not a success.
    fake = _executable(tmp_path / "fake-browser", "#!/bin/sh\nexit 0\n")

    with pytest.raises(ReportError, match=r"browser failed to produce a PDF \(exit 0\): no output"):
        pdf.html_to_pdf("<html></html>", tmp_path / "out.pdf", browser=str(fake))


def test_html_to_pdf_wraps_an_unrunnable_browser(tmp_path: Path) -> None:
    with pytest.raises(ReportError, match=r"could not run the browser"):
        pdf.html_to_pdf("<html></html>", tmp_path / "out.pdf", browser=str(tmp_path / "does-not-exist"))


def test_html_to_pdf_times_out_instead_of_hanging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf, "_TIMEOUT_SECONDS", 0.2)
    fake = _executable(tmp_path / "fake-browser", "#!/bin/sh\nsleep 5\n")

    with pytest.raises(ReportError, match=r"timed out after .* rendering the PDF"):
        pdf.html_to_pdf("<html></html>", tmp_path / "out.pdf", browser=str(fake))
