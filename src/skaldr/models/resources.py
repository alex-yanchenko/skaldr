from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path


def _resource(name: str) -> Traversable:
    return resources.files("skaldr").joinpath(name)


def package_text(name: str) -> str:
    """Text of a bundled package resource (the stylesheet, a template)."""
    return _resource(name).read_text(encoding="utf-8")


def package_path(name: str) -> Path:
    """Filesystem path to a bundled resource. skaldr wheels install unzipped, so this resolves
    to a real path (suitable for reading or copying a bundled file, e.g. the skill dir)."""
    return Path(str(_resource(name)))
