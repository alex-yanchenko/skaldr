from pathlib import Path

import pytest

from skaldr.errors import ReportError
from skaldr.models import content_files, load_report

_TEXT_BLOCK = "- type: text\n  body: from the fragment\n"
_TEXT_BLOCK_JSON = [{"type": "text", "body": "from the fragment", "muted": False, "span": None}]


def _document_including(target: str) -> str:
    return f"version: 1\nmeta:\n  title: T\nblocks: !include {target}\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _outside_message(target: str, document: Path, fragment: Path, root: Path, kind: str) -> str:
    return (
        f"!include {target} in {document} resolves to {fragment.resolve()}, outside {root.resolve()}, "
        f"the {kind} that holds the document"
    )


def test_an_include_in_a_sibling_folder_of_the_same_repository_works(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(repo / "shared" / "blocks.yaml", _TEXT_BLOCK)
    document = _write(
        repo / "docs" / "reports" / "main.yaml", _document_including("../../shared/blocks.yaml")
    )

    assert load_report(document).model_dump(mode="json")["blocks"] == _TEXT_BLOCK_JSON


def test_a_git_file_in_a_worktree_marks_the_root_like_a_git_folder(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    _write(worktree / ".git", "gitdir: /elsewhere\n")
    _write(worktree / "shared" / "blocks.yaml", _TEXT_BLOCK)
    document = _write(worktree / "docs" / "main.yaml", _document_including("../shared/blocks.yaml"))

    assert load_report(document).model_dump(mode="json")["blocks"] == _TEXT_BLOCK_JSON


def test_an_include_two_levels_above_the_document_outside_the_repository_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    secret = _write(tmp_path / "outside" / "secret.yaml", "token: synthetic-token\n")
    target = "../../outside/secret.yaml"
    document = _write(repo / "docs" / "main.yaml", _document_including(target))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == _outside_message(target, document, secret, repo, "git work tree")


def test_a_nested_include_that_climbs_out_of_the_repository_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    secret = _write(tmp_path / "outside" / "secret.yaml", "token: synthetic-token\n")
    target = "../../outside/secret.yaml"
    fragment = _write(repo / "shared" / "outer.yaml", f"!include {target}\n")
    document = _write(repo / "main.yaml", _document_including("shared/outer.yaml"))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == _outside_message(
        target, repo / "shared" / "outer.yaml", secret, repo, "git work tree"
    )
    assert fragment.exists()


def test_a_symlinked_include_pointing_outside_the_repository_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    secret = _write(tmp_path / "outside" / "secret.yaml", "token: synthetic-token\n")
    (repo / "blocks.yaml").symlink_to(secret)
    document = _write(repo / "main.yaml", _document_including("blocks.yaml"))

    with pytest.raises(ReportError) as refused:
        load_report(document)

    assert str(refused.value) == _outside_message("blocks.yaml", document, secret, repo, "git work tree")


def test_a_symlinked_include_pointing_to_another_file_inside_the_repository_works(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    real = _write(repo / "shared" / "blocks.yaml", _TEXT_BLOCK)
    (repo / "alias.yaml").symlink_to(real)
    document = _write(repo / "main.yaml", _document_including("alias.yaml"))

    assert load_report(document).model_dump(mode="json")["blocks"] == _TEXT_BLOCK_JSON


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

    assert load_report(document).model_dump(mode="json")["blocks"] == _TEXT_BLOCK_JSON


def test_content_files_refuses_an_include_outside_the_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    secret = _write(tmp_path / "outside" / "secret.yaml", "token: synthetic-token\n")
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
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(repo / "shared" / "blocks.yaml", _TEXT_BLOCK)
    _write(repo / "docs" / "one.yaml", _part_including("../shared/blocks.yaml"))
    index = _write(repo / "docs" / "index.yaml", _index_over("one.yaml"))

    assert load_report(index).model_dump(mode="json")["blocks"][0]["blocks"] == _TEXT_BLOCK_JSON


def test_an_include_inside_an_index_part_that_leaves_the_repository_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    secret = _write(tmp_path / "outside" / "secret.yaml", "token: synthetic-token\n")
    target = "../../outside/secret.yaml"
    part = _write(repo / "docs" / "one.yaml", _part_including(target))
    index = _write(repo / "docs" / "index.yaml", _index_over("one.yaml"))

    with pytest.raises(ReportError) as refused:
        load_report(index)

    assert str(refused.value) == _outside_message(target, part, secret, repo, "git work tree")
