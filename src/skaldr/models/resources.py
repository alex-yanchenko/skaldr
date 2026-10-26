import sys
from importlib import resources
from pathlib import Path

# Traversable moved to importlib.resources.abc in 3.11; on 3.10 it lives in importlib.abc.
if sys.version_info >= (3, 11):
    from importlib.resources.abc import Traversable
else:
    from importlib.abc import Traversable


def _resource(name: str) -> Traversable:
    return resources.files("skaldr").joinpath(name)


def package_text(name: str) -> str:
    """Text of a bundled package resource (the stylesheet, a template)."""
    return _resource(name).read_text(encoding="utf-8")


def package_path(name: str) -> Path:
    """Filesystem path to a bundled resource. skaldr wheels install unzipped, so this resolves
    to a real path (suitable for reading or copying a bundled file, e.g. the skill dir)."""
    return Path(str(_resource(name)))
