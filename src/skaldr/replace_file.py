import errno
import os
import shutil
import tempfile
from pathlib import Path


def resolved_path(path: Path) -> Path:
    try:
        resolved = path.resolve()
    except RuntimeError as err:
        raise OSError(errno.ELOOP, os.strerror(errno.ELOOP), str(path)) from err
    if resolved.is_symlink():
        raise OSError(errno.ELOOP, os.strerror(errno.ELOOP), str(path))
    return resolved


def _rewrite_in_place(path: Path) -> bool:
    if not os.access(path.parent, os.W_OK):
        return True
    return path.is_file() and path.stat().st_nlink > 1


def replace_file(path: Path, text: str) -> None:
    path = resolved_path(path)
    if path.is_dir():
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(path))
    encoded = text.encode("utf-8")
    if _rewrite_in_place(path):
        path.write_bytes(encoded)
        return
    with tempfile.TemporaryDirectory(prefix=".skaldr-write-", dir=path.parent) as staging:
        staged = Path(staging) / path.name
        staged.write_bytes(encoded)
        if path.is_file():
            shutil.copymode(path, staged)
        staged.replace(path)
