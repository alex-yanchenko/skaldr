import subprocess
import sys

PUBLISH_RUNTIME = "skaldr.publish"
PUBLISH_EXTRA = ("authlib", "httpx2", "keyring")
DOCUMENT_MODULES = ("skaldr.models", "skaldr.render", "skaldr.export", "skaldr.compute")


def _modules_loaded_by(module: str) -> list[str]:
    script = f"import sys\nimport {module}\nprint('\\n'.join(sorted(sys.modules)))"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def _is_in_package(name: str, package: str) -> bool:
    return name == package or name.startswith(f"{package}.")


def test_loading_a_document_never_loads_the_publish_runtime_or_its_extra() -> None:
    loaded = _modules_loaded_by("skaldr.models")

    assert [
        name
        for name in loaded
        if _is_in_package(name, PUBLISH_RUNTIME)
        or any(_is_in_package(name, extra) for extra in PUBLISH_EXTRA)
    ] == []


def test_the_publish_block_schema_loads_without_the_document_model() -> None:
    loaded = _modules_loaded_by("skaldr.publish_block")

    assert [
        name
        for name in loaded
        if _is_in_package(name, PUBLISH_RUNTIME)
        or any(_is_in_package(name, document_module) for document_module in DOCUMENT_MODULES)
    ] == []


def test_the_service_vocabulary_loads_on_its_own() -> None:
    loaded = _modules_loaded_by("skaldr.services")

    assert [name for name in loaded if _is_in_package(name, "skaldr")] == ["skaldr", "skaldr.services"]
