import contextlib
import errno
import os
import shutil
import tempfile
from pathlib import Path

from skaldr.errors import ReadOnlyFileError


def resolved_path(path: Path) -> Path:
    resolved = Path(os.path.realpath(path))
    if resolved.is_symlink():
        raise OSError(errno.ELOOP, os.strerror(errno.ELOOP), str(path))
    return resolved


def _refuse_a_read_only_file(path: Path) -> None:
    if path.is_file() and not os.access(path, os.W_OK):
        raise ReadOnlyFileError(
            errno.EACCES, "the file is read-only, so skaldr leaves it as it is", str(path)
        )


def _rewrite_in_place(path: Path) -> bool:
    if not os.access(path.parent, os.W_OK):
        return True
    return path.is_file() and path.stat().st_nlink > 1


def _write_and_flush(path: Path, encoded: bytes) -> None:
    path.write_bytes(encoded)
    with path.open("r+b") as written_file:
        os.fsync(written_file.fileno())


def _write_in_place_restoring_on_failure(path: Path, encoded: bytes) -> None:
    earlier = path.read_bytes() if path.is_file() else None
    try:
        _write_and_flush(path, encoded)
    except BaseException:
        if earlier is not None:
            with contextlib.suppress(OSError):
                path.write_bytes(earlier)
        raise


def _flush_directory(directory: Path) -> None:
    if os.name != "posix":
        return
    with contextlib.suppress(OSError):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def refuse_an_unreplaceable_target(path: Path) -> Path:
    path = resolved_path(path)
    if path.is_dir():
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(path))
    _refuse_a_read_only_file(path)
    return path


def replace_bytes(path: Path, encoded: bytes) -> None:
    path = refuse_an_unreplaceable_target(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _rewrite_in_place(path):
        _write_in_place_restoring_on_failure(path, encoded)
        return
    with tempfile.TemporaryDirectory(prefix=".skaldr-write-", dir=path.parent) as staging:
        staged = Path(staging) / path.name
        _write_and_flush(staged, encoded)
        if path.is_file():
            shutil.copymode(path, staged)
        staged.replace(path)
    _flush_directory(path.parent)


def replace_file(path: Path, text: str) -> None:
    replace_bytes(path, text.encode("utf-8"))
