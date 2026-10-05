from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version


def skaldr_version() -> str:
    try:
        return package_version("skaldr")
    except PackageNotFoundError:
        return "unknown"
