from pathlib import Path
from typing import Any, Literal

import pytest

from skaldr.errors import ReportError
from skaldr.models import content_files, load_report
from skaldr.models.loading import _is_git_marker  # pyright: ignore[reportPrivateUsage]

_TEXT_BLOCK = "- type: text\n  body: from the fragment\n"
_TEXT_BLOCK_JSON = [{"type": "text", "body": "from the fragment", "muted": False, "span": None}]
_SECRET = "token: synthetic-token\n"


def _document_including(target: str) -> str:
    return f"version: 1\nmeta:\n  title: T\nblocks: !include {target}\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _repository(root: Path) -> Path:
    (root / ".git").mkdir(parents=True)
    return root


def _loaded_blocks(path: Path) -> list[dict[str, Any]]:
    return load_report(path).model_dump(mode="json")["blocks"]


def _outside_message(
    target: str, document: Path, fragment: Path, root: Path, kind: Literal["git work tree", "folder"]
) -> str:
    return (
        f"!include {target} in {document} resolves to {fragment.resolve()}, outside {root.resolve()}, "
        f"the {kind} that holds the document"
    )


@pytest.fixture(autouse=True)
def only_markers_inside_the_test_folder_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inside = tmp_path.resolve()

    def is_a_marker_inside(folder: Path) -> bool:
        return folder.is_relative_to(inside) and _is_git_marker(folder)

    monkeypatch.setattr("skaldr.models.loading._is_git_marker", is_a_marker_inside)


def test_an_include_in_a_sibling_folder_of_the_same_repository_works(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    _write(repo / "shared" / "blocks.yaml", _TEXT_BLOCK)
    document = _write(
        repo / "docs" / "reports" / "main.yaml", _document_including("../../shared/blocks.yaml")
    )

    assert _loaded_blocks(document) == _TEXT_BLOCK_JSON


def test_a_git_file_in_a_worktree_marks_the_root_like_a_git_folder(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    _write(worktree / ".git", "gitdir: /elsewhere\n")
    _write(worktree / "shared" / "blocks.yaml", _TEXT_BLOCK)
    document = _write(worktree / "docs" / "main.yaml", _document_including("../shared/blocks.yaml"))

    assert _loaded_blocks(document) == _TEXT_BLOCK_JSON


def test_a_plain_file_named_git_does_not_mark_a_root(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    _write(repo / "docs" / ".git", "just some notes\n")
    _write(repo / "shared" / "blocks.yaml", _TEXT_BLOCK)
    document = _write(repo / "docs" / "main.yaml", _document_including("../shared/blocks.yaml"))

    assert _loaded_blocks(document) == _TEXT_BLOCK_JSON


def test_a_plain_file_named_git_with_no_repository_above_leaves_the_folder_as_the_root(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "docs" / ".git", "just some notes\n")
    neighbour = _write(tmp_path / "shared" / "blocks.yaml", _TEXT_BLOCK)
    target = "../shared/blocks.yaml"
    document = _write(tmp_path / "docs" / "main.yaml", _document_including(target))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == _outside_message(target, document, neighbour, tmp_path / "docs", "folder")


def test_an_include_two_levels_above_the_document_outside_the_repository_is_refused(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    secret = _write(tmp_path / "outside" / "secret.yaml", _SECRET)
    target = "../../outside/secret.yaml"
    document = _write(repo / "docs" / "main.yaml", _document_including(target))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == _outside_message(target, document, secret, repo, "git work tree")


def test_a_nested_include_that_climbs_out_of_the_repository_is_refused(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    secret = _write(tmp_path / "outside" / "secret.yaml", _SECRET)
    target = "../../outside/secret.yaml"
    fragment = _write(repo / "shared" / "outer.yaml", f"!include {target}\n")
    document = _write(repo / "main.yaml", _document_including("shared/outer.yaml"))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == _outside_message(target, fragment, secret, repo, "git work tree")


def test_a_symlinked_include_pointing_outside_the_repository_is_refused(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    secret = _write(tmp_path / "outside" / "secret.yaml", _SECRET)
    (repo / "blocks.yaml").symlink_to(secret)
    document = _write(repo / "main.yaml", _document_including("blocks.yaml"))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == _outside_message("blocks.yaml", document, secret, repo, "git work tree")


def test_a_symlinked_include_pointing_to_another_file_inside_the_repository_works(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    real = _write(repo / "shared" / "blocks.yaml", _TEXT_BLOCK)
    (repo / "alias.yaml").symlink_to(real)
    document = _write(repo / "main.yaml", _document_including("alias.yaml"))

    assert _loaded_blocks(document) == _TEXT_BLOCK_JSON


def test_without_a_repository_the_documents_own_folder_is_the_root(tmp_path: Path) -> None:
    neighbour = _write(tmp_path / "neighbour.yaml", _TEXT_BLOCK)
    target = "../neighbour.yaml"
    document = _write(tmp_path / "docs" / "main.yaml", _document_including(target))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == _outside_message(target, document, neighbour, tmp_path / "docs", "folder")


def test_without_a_repository_a_subfolder_of_the_documents_folder_works(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "shared" / "blocks.yaml", _TEXT_BLOCK)
    document = _write(tmp_path / "docs" / "main.yaml", _document_including("shared/blocks.yaml"))

    assert _loaded_blocks(document) == _TEXT_BLOCK_JSON


def test_without_a_repository_a_nested_include_may_reach_the_top_documents_folder(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "b.yaml", _TEXT_BLOCK)
    _write(tmp_path / "docs" / "sub" / "a.yaml", "!include ../b.yaml\n")
    document = _write(tmp_path / "docs" / "main.yaml", _document_including("sub/a.yaml"))

    assert _loaded_blocks(document) == _TEXT_BLOCK_JSON


def test_without_a_repository_a_nested_include_may_not_leave_the_top_documents_folder(tmp_path: Path) -> None:
    neighbour = _write(tmp_path / "b.yaml", _TEXT_BLOCK)
    nested = _write(tmp_path / "docs" / "sub" / "a.yaml", "!include ../../b.yaml\n")
    document = _write(tmp_path / "docs" / "main.yaml", _document_including("sub/a.yaml"))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == _outside_message(
        "../../b.yaml", nested, neighbour, tmp_path / "docs", "folder"
    )


def test_content_files_lists_a_nested_include_that_reaches_the_top_documents_folder(tmp_path: Path) -> None:
    included = _write(tmp_path / "docs" / "b.yaml", _TEXT_BLOCK)
    nested = _write(tmp_path / "docs" / "sub" / "a.yaml", "!include ../b.yaml\n")
    document = _write(tmp_path / "docs" / "main.yaml", _document_including("sub/a.yaml"))

    assert content_files(document) == (document.resolve(), nested.resolve(), included.resolve())


def test_content_files_refuses_an_include_outside_the_root(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    secret = _write(tmp_path / "outside" / "secret.yaml", _SECRET)
    target = "../outside/secret.yaml"
    document = _write(repo / "main.yaml", _document_including(target))

    with pytest.raises(ReportError) as refused:
        content_files(document)

    assert str(refused.value) == _outside_message(target, document, secret, repo, "git work tree")


def _index_over(part: str) -> str:
    return f"version: 1\nmeta:\n  title: Index\nindex:\n  parts:\n    - {part}\n"


def _part_including(target: str) -> str:
    return f"version: 1\nmeta:\n  title: Part\nblocks: !include {target}\n"


def test_an_include_inside_an_index_part_may_reach_the_repository_outside_the_parts_folder(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path / "repo")
    _write(repo / "shared" / "blocks.yaml", _TEXT_BLOCK)
    _write(repo / "docs" / "one.yaml", _part_including("../shared/blocks.yaml"))
    index = _write(repo / "docs" / "index.yaml", _index_over("one.yaml"))

    assert _loaded_blocks(index)[0]["blocks"] == _TEXT_BLOCK_JSON


def test_an_include_inside_an_index_part_that_leaves_the_repository_is_refused(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    secret = _write(tmp_path / "outside" / "secret.yaml", _SECRET)
    target = "../../outside/secret.yaml"
    part = _write(repo / "docs" / "one.yaml", _part_including(target))
    index = _write(repo / "docs" / "index.yaml", _index_over("one.yaml"))

    with pytest.raises(ReportError) as refused:
        load_report(index)

    assert str(refused.value) == _outside_message(target, part, secret, repo, "git work tree")


def test_without_a_repository_an_include_in_a_part_may_reach_the_index_folder_from_a_subfolder(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "d" / "sibling.yaml", _TEXT_BLOCK)
    _write(tmp_path / "d" / "sub" / "one.yaml", _part_including("../sibling.yaml"))
    index = _write(tmp_path / "d" / "index.yaml", _index_over("sub/one.yaml"))

    assert _loaded_blocks(index)[0]["blocks"] == _TEXT_BLOCK_JSON


def test_without_a_repository_an_include_in_a_part_may_not_leave_the_index_folder(tmp_path: Path) -> None:
    neighbour = _write(tmp_path / "sibling.yaml", _TEXT_BLOCK)
    part = _write(tmp_path / "d" / "sub" / "one.yaml", _part_including("../../sibling.yaml"))
    index = _write(tmp_path / "d" / "index.yaml", _index_over("sub/one.yaml"))

    with pytest.raises(ReportError) as refused:
        load_report(index)

    assert str(refused.value) == _outside_message(
        "../../sibling.yaml", part, neighbour, tmp_path / "d", "folder"
    )


@pytest.fixture
def folders_named_loop_cannot_be_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.resolve

    def resolve(self: Path, strict: bool = False) -> Path:
        if self.name == "loop":
            raise RuntimeError(f"Symlink loop from {self}")
        return original(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)


@pytest.mark.usefixtures("folders_named_loop_cannot_be_resolved")
def test_a_document_folder_that_cannot_be_resolved_is_a_report_error(tmp_path: Path) -> None:
    document = _write(tmp_path / "loop" / "main.yaml", _document_including("blocks.yaml"))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == f"could not resolve {document}: Symlink loop from {tmp_path / 'loop'}"


@pytest.mark.usefixtures("folders_named_loop_cannot_be_resolved")
def test_an_include_that_cannot_be_resolved_is_a_report_error(tmp_path: Path) -> None:
    document = _write(tmp_path / "main.yaml", _document_including("loop"))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert (
        str(refused.value) == f"could not resolve {tmp_path / 'loop'}: Symlink loop from {tmp_path / 'loop'}"
    )
