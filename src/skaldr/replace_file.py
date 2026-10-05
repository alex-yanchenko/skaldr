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


def replace_file(path: Path, text: str) -> None:
    path = resolved_path(path)
    if path.is_dir():
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(path))
    _refuse_a_read_only_file(path)
    encoded = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if _rewrite_in_place(path):
        path.write_bytes(encoded)
        return
    with tempfile.TemporaryDirectory(prefix=".skaldr-write-", dir=path.parent) as staging:
        staged = Path(staging) / path.name
        staged.write_bytes(encoded)
        if path.is_file():
            shutil.copymode(path, staged)
        staged.replace(path)
