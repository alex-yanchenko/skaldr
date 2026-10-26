from pathlib import Path

import pytest

from skaldr.errors import ReportError
from skaldr.models import content_files, load_report, parse_report, read_text_file
from tests.factories import make_report


def test_malformed_yaml_is_a_report_error(tmp_path: Path) -> None:
    data_path = tmp_path / "broken.yaml"
    data_path.write_text("blocks: [unclosed\nversion: 1", encoding="utf-8")

    with pytest.raises(ReportError, match=r"invalid YAML in .*broken\.yaml"):
        load_report(data_path)


def test_missing_file_is_a_report_error(tmp_path: Path) -> None:
    with pytest.raises(ReportError, match=r"file not found: .*nope\.yaml"):
        load_report(tmp_path / "nope.yaml")


def test_unreadable_file_is_a_report_error(tmp_path: Path) -> None:
    with pytest.raises(ReportError, match=r"could not read .*"):
        read_text_file(tmp_path)


_MAIN_WITH_INCLUDE = "version: 1\nmeta:\n  title: T\nblocks: !include blocks.yaml\n"


def test_include_splices_a_fragment(tmp_path: Path) -> None:
    (tmp_path / "blocks.yaml").write_text("- type: text\n  body: from fragment\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(_MAIN_WITH_INCLUDE, encoding="utf-8")

    report = load_report(tmp_path / "main.yaml")

    assert report.model_dump(mode="json")["blocks"] == [
        {"type": "text", "body": "from fragment", "muted": False, "span": None}
    ]


def test_include_of_a_single_item_inside_a_sequence(tmp_path: Path) -> None:
    (tmp_path / "one.yaml").write_text("type: text\nbody: just me\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(
        "version: 1\nmeta:\n  title: T\nblocks:\n  - !include one.yaml\n", encoding="utf-8"
    )

    report = load_report(tmp_path / "main.yaml")

    assert report.model_dump(mode="json")["blocks"] == [
        {"type": "text", "body": "just me", "muted": False, "span": None}
    ]


def test_include_resolves_paths_relative_to_each_including_file(tmp_path: Path) -> None:
    # main includes shared/frag.yaml; frag then includes deep.yaml, which lives next to FRAG (in
    # shared/), not next to main — so the path must resolve relative to frag's own dir, not the cwd
    # or the top file's dir.
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "deep.yaml").write_text("- type: text\n  body: deep\n", encoding="utf-8")
    (shared / "frag.yaml").write_text("!include deep.yaml\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(
        "version: 1\nmeta:\n  title: T\nblocks: !include shared/frag.yaml\n", encoding="utf-8"
    )

    report = load_report(tmp_path / "main.yaml")

    assert report.model_dump(mode="json")["blocks"] == [
        {"type": "text", "body": "deep", "muted": False, "span": None}
    ]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(
            make_report(meta={"title": "bad \ud800 title"}),
            "invalid content data: meta.title: U+D800 is a lone surrogate, which a page cannot hold",
            id="field",
        ),
        pytest.param(
            make_report(blocks=[{"type": "text", "body": "ok"}, {"type": "list", "items": ["a", "\udfff"]}]),
            "invalid content data: blocks.1.items.1: U+DFFF is a lone surrogate, which a page cannot hold",
            id="list-item",
        ),
        pytest.param(
            make_report(badges={"K\udc80": {"label": "L", "tone": "info", "legend": "x"}}),
            "invalid content data: badges: the key 'K\\udc80' holds U+DC80, a lone surrogate, which a page "
            "cannot hold",
            id="mapping-key",
        ),
    ],
)
def test_a_lone_surrogate_is_refused_naming_where_it_sits(data: dict[str, object], message: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(data)

    assert str(raised.value) == message


def test_content_files_lists_the_file_and_every_fragment_it_includes_in_load_order(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "deep.yaml").write_text("- type: text\n  body: deep\n", encoding="utf-8")
    (shared / "frag.yaml").write_text("!include deep.yaml\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(
        "version: 1\nmeta:\n  title: T\nblocks: !include shared/frag.yaml\n", encoding="utf-8"
    )

    files = content_files(tmp_path / "main.yaml")

    assert files == (
        (tmp_path / "main.yaml").resolve(),
        (shared / "frag.yaml").resolve(),
        (shared / "deep.yaml").resolve(),
    )


def test_missing_include_target_is_a_report_error(tmp_path: Path) -> None:
    (tmp_path / "main.yaml").write_text(_MAIN_WITH_INCLUDE, encoding="utf-8")

    with pytest.raises(ReportError, match=r"file not found: .*blocks\.yaml"):
        load_report(tmp_path / "main.yaml")


def test_circular_include_is_a_report_error(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("!include b.yaml\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("!include a.yaml\n", encoding="utf-8")

    with pytest.raises(ReportError, match=r"circular !include:.*a\.yaml.*b\.yaml.*a\.yaml"):
        load_report(tmp_path / "a.yaml")


def test_self_include_is_a_report_error(tmp_path: Path) -> None:
    (tmp_path / "loop.yaml").write_text("!include loop.yaml\n", encoding="utf-8")

    with pytest.raises(ReportError, match=r"circular !include"):
        load_report(tmp_path / "loop.yaml")


def test_include_of_a_non_scalar_is_a_report_error(tmp_path: Path) -> None:
    (tmp_path / "main.yaml").write_text("version: 1\nblocks: !include [a, b]\n", encoding="utf-8")

    with pytest.raises(ReportError, match=r"!include in .*main\.yaml takes a single file path"):
        load_report(tmp_path / "main.yaml")


def test_include_with_no_path_is_a_report_error(tmp_path: Path) -> None:
    (tmp_path / "main.yaml").write_text('version: 1\nblocks: !include ""\n', encoding="utf-8")

    with pytest.raises(ReportError, match=r"!include in .*main\.yaml needs a file path"):
        load_report(tmp_path / "main.yaml")


def test_absolute_include_path_is_a_report_error(tmp_path: Path) -> None:
    # an absolute target would read outside the fragment set and silently break "relative to the
    # including file" — path.parent / "/abs" collapses to "/abs" — so it's rejected up front.
    (tmp_path / "main.yaml").write_text("version: 1\nblocks: !include /nope/abs.yaml\n", encoding="utf-8")

    with pytest.raises(ReportError, match=r"must be a relative path, not absolute: /nope/abs\.yaml"):
        load_report(tmp_path / "main.yaml")


def test_include_reuses_one_fragment_from_two_sites(tmp_path: Path) -> None:
    (tmp_path / "frag.yaml").write_text("type: text\nbody: reused\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(
        "version: 1\nmeta:\n  title: T\nblocks:\n  - !include frag.yaml\n  - !include frag.yaml\n",
        encoding="utf-8",
    )

    report = load_report(tmp_path / "main.yaml")

    reused = {"type": "text", "body": "reused", "muted": False, "span": None}
    assert report.model_dump(mode="json")["blocks"] == [reused, reused]


def test_include_works_under_a_non_blocks_key(tmp_path: Path) -> None:
    (tmp_path / "meta.yaml").write_text("title: From Fragment\n", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(
        "version: 1\nmeta: !include meta.yaml\nblocks:\n  - type: text\n    body: x\n", encoding="utf-8"
    )

    report = load_report(tmp_path / "main.yaml")

    assert report.model_dump(mode="json")["meta"]["title"] == "From Fragment"


def test_empty_included_fragment_is_a_report_error(tmp_path: Path) -> None:
    # an empty fragment parses to None; splicing None in for `blocks` must fail validation cleanly,
    # not raise a raw exception downstream.
    (tmp_path / "blocks.yaml").write_text("", encoding="utf-8")
    (tmp_path / "main.yaml").write_text(_MAIN_WITH_INCLUDE, encoding="utf-8")

    with pytest.raises(ReportError, match=r"blocks:.*valid list"):
        load_report(tmp_path / "main.yaml")


def test_include_chain_deeper_than_the_cap_is_a_report_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a very deep non-cyclic chain must surface as a ReportError, not a raw RecursionError
    monkeypatch.setattr("skaldr.models.loading._MAX_INCLUDE_DEPTH", 1)
    (tmp_path / "a.yaml").write_text("!include b.yaml\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("- type: text\n  body: x\n", encoding="utf-8")

    with pytest.raises(ReportError, match=r"nested more than 1 deep"):
        load_report(tmp_path / "a.yaml")


def test_symlink_loop_is_a_report_error(tmp_path: Path) -> None:
    # a symlink loop must surface as a typed ReportError, never a raw traceback. The message is
    # version-dependent: on Python <=3.12 Path.resolve() raises on the loop (→ "could not resolve");
    # 3.13+ tolerates it, so the broken link is caught downstream as "file not found".
    (tmp_path / "a.yaml").symlink_to(tmp_path / "b.yaml")
    (tmp_path / "b.yaml").symlink_to(tmp_path / "a.yaml")

    with pytest.raises(ReportError, match=r"could not resolve|file not found"):
        load_report(tmp_path / "a.yaml")


def test_non_mapping_payload_is_a_report_error() -> None:
    with pytest.raises(ReportError, match=r"Input should be a valid dictionary"):
        parse_report(["not", "a", "mapping"])
