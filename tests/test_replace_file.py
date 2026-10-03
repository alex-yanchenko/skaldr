import errno
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from skaldr.replace_file import replace_file


@pytest.fixture
def read_only_directory(tmp_path: Path) -> Iterator[Path]:
    directory = tmp_path / "ro"
    directory.mkdir()
    yield directory
    directory.chmod(0o755)


def test_a_new_file_is_written_with_its_text(tmp_path: Path) -> None:
    path = tmp_path / "page.html"

    replace_file(path, "new page")

    assert (path.read_text(encoding="utf-8"), sorted(tmp_path.iterdir())) == ("new page", [path])


def test_an_existing_file_keeps_its_mode(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text("earlier page", encoding="utf-8")
    path.chmod(0o640)

    replace_file(path, "new page")

    assert (path.read_text(encoding="utf-8"), stat.S_IMODE(path.stat().st_mode)) == ("new page", 0o640)


def test_a_symlink_gets_the_text_in_its_target_and_stays_a_link(tmp_path: Path) -> None:
    target = tmp_path / "dotfiles" / "CLAUDE.md"
    target.parent.mkdir()
    target.write_text("earlier", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "CLAUDE.md"
    link.symlink_to(target)

    replace_file(link, "new text")

    assert (
        link.is_symlink(),
        target.read_text(encoding="utf-8"),
        stat.S_IMODE(target.stat().st_mode),
        sorted(target.parent.iterdir()),
    ) == (True, "new text", 0o600, [target])


def test_a_dangling_symlink_creates_its_target(tmp_path: Path) -> None:
    target = tmp_path / "target.html"
    link = tmp_path / "page.html"
    link.symlink_to(target)

    replace_file(link, "new page")

    assert (link.is_symlink(), target.read_text(encoding="utf-8")) == (True, "new page")


def test_a_hard_linked_file_is_updated_under_every_name(tmp_path: Path) -> None:
    first = tmp_path / "first.html"
    first.write_text("earlier page", encoding="utf-8")
    second = tmp_path / "second.html"
    os.link(first, second)

    replace_file(first, "new page")

    assert (
        first.read_text(encoding="utf-8"),
        second.read_text(encoding="utf-8"),
        first.stat().st_nlink,
    ) == ("new page", "new page", 2)


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a read-only directory")
def test_a_writable_file_in_a_read_only_directory_is_rewritten_in_place(read_only_directory: Path) -> None:
    path = read_only_directory / "page.html"
    path.write_text("earlier page", encoding="utf-8")
    read_only_directory.chmod(0o555)

    replace_file(path, "new page")

    assert (path.read_text(encoding="utf-8"), sorted(read_only_directory.iterdir())) == ("new page", [path])


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a read-only directory")
def test_a_new_file_in_a_read_only_directory_fails_naming_the_file(read_only_directory: Path) -> None:
    path = read_only_directory / "page.html"
    read_only_directory.chmod(0o555)

    with pytest.raises(PermissionError) as raised:
        replace_file(path, "new page")

    assert (raised.value.errno, raised.value.filename) == (errno.EACCES, str(path))


def test_a_directory_at_the_path_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.mkdir()

    with pytest.raises(IsADirectoryError) as raised:
        replace_file(path, "new page")

    assert (raised.value.errno, raised.value.filename) == (errno.EISDIR, str(path))


def test_a_symlink_to_a_directory_is_refused_and_left_in_place(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    link = tmp_path / "page.md"
    link.symlink_to(directory)

    with pytest.raises(IsADirectoryError) as raised:
        replace_file(link, "new page")

    assert (raised.value.errno, raised.value.filename, link.is_symlink()) == (
        errno.EISDIR,
        str(directory),
        True,
    )


def test_a_symlink_loop_is_an_os_error_naming_the_path(tmp_path: Path) -> None:
    first = tmp_path / "loop1.html"
    second = tmp_path / "loop2.html"
    first.symlink_to(second)
    second.symlink_to(first)

    with pytest.raises(OSError) as raised:
        replace_file(first, "new page")

    assert (raised.value.errno, raised.value.filename) == (errno.ELOOP, str(first))


def test_text_that_cannot_be_encoded_leaves_the_earlier_file_untouched(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text("earlier page", encoding="utf-8")

    with pytest.raises(UnicodeEncodeError):
        replace_file(path, "lone \ud800 surrogate")

    assert (path.read_text(encoding="utf-8"), sorted(tmp_path.iterdir())) == ("earlier page", [path])
