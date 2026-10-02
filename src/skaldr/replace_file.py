import errno
import os
import shutil
import tempfile
from pathlib import Path


def replace_file(path: Path, text: str) -> None:
    if path.is_dir() and not path.is_symlink():
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(path))
    with tempfile.TemporaryDirectory(prefix=".skaldr-write-", dir=path.parent) as staging:
        staged = Path(staging) / path.name
        staged.write_text(text, encoding="utf-8")
        if path.is_file() and not path.is_symlink():
            shutil.copymode(path, staged)
        staged.replace(path)
