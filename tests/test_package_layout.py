import subprocess
import sys

import pytest

PUBLISH_RUNTIME = "skaldr.publish"
PUBLISH_EXTRA = ("authlib", "httpx2", "keyring")
DOCUMENT_MODULES = ("skaldr.models", "skaldr.render", "skaldr.export", "skaldr.compute")
LOADED_CLEANLY = (0, "")


def _loaded_modules(*imports: str) -> tuple[int, str, list[str]]:
    script = "\n".join(
        ["import sys", *(f"import {module}" for module in imports), "print('\\n'.join(sorted(sys.modules)))"]
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
    return result.returncode, result.stderr, result.stdout.splitlines()


def _is_in_package(name: str, package: str) -> bool:
    return name == package or name.startswith(f"{package}.")


def _is_publish_runtime_or_extra(name: str) -> bool:
    return any(_is_in_package(name, package) for package in (PUBLISH_RUNTIME, *PUBLISH_EXTRA))


@pytest.mark.parametrize("module", [*DOCUMENT_MODULES, "skaldr.cli"])
def test_a_document_side_module_never_loads_the_publish_runtime_or_its_extra(module: str) -> None:
    returncode, stderr, loaded = _loaded_modules(module)

    assert (returncode, stderr) == LOADED_CLEANLY
    assert [name for name in loaded if _is_publish_runtime_or_extra(name)] == []


def test_the_publish_block_schema_loads_without_the_document_model() -> None:
    returncode, stderr, loaded = _loaded_modules("skaldr.publish_block")

    assert (returncode, stderr) == LOADED_CLEANLY
    assert [
        name
        for name in loaded
        if _is_in_package(name, PUBLISH_RUNTIME)
        or any(_is_in_package(name, document_module) for document_module in DOCUMENT_MODULES)
    ] == []


def test_the_service_vocabulary_loads_nothing_outside_the_standard_library() -> None:
    _, _, at_startup = _loaded_modules()
    returncode, stderr, loaded = _loaded_modules("skaldr.services")

    assert (returncode, stderr) == LOADED_CLEANLY
    assert [
        name
        for name in sorted(set(loaded) - set(at_startup))
        if name.split(".")[0] not in sys.stdlib_module_names
    ] == ["skaldr", "skaldr.services"]
