import base64
import json
from pathlib import Path
from typing import Any

import pytest

from skaldr.errors import ExportRejectedError, ReportError
from skaldr.export import EXPORT_MANIFEST, ExportResult, ExportTarget, export_markdown, render_export
from skaldr.models import load_report, parse_report
from tests.factories import make_report, write_report

PNG_BYTES = b"\x89PNG\r\n\x1a\nsynthetic aisle photo"
JPEG_BYTES = b"\xff\xd8\xffsynthetic dock photo"
SVG_TEXT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect width="4" height="4"/></svg>'
PNG_URI = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
JPEG_URI = "data:image/jpeg;base64," + base64.b64encode(JPEG_BYTES).decode("ascii")
PERCENT_ENCODED_SVG_URI = "data:image/svg+xml," + SVG_TEXT.replace("<", "%3C").replace(">", "%3E")
ACCEPTED_TYPES = "png, jpeg, gif, webp, svg+xml, avif or bmp"
GIVE_AN_IMAGE_DATA_URI = (
    f"give a data: URI holding a {ACCEPTED_TYPES} image, or host the image and give its https address"
)


def _image(src: str, alt: str = "Aisle 12") -> dict[str, Any]:
    return {"type": "image", "src": src, "alt": alt}


def _exported(tmp_path: Path, blocks: list[dict[str, Any]]) -> tuple[ExportResult, Path]:
    report = load_report(write_report(tmp_path, make_report(blocks=blocks)))
    out_dir = tmp_path / "out"
    return export_markdown(report, out_dir), out_dir


def _folder_bytes(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir())}


def _manifest_files(folder: Path) -> list[str]:
    return json.loads((folder / EXPORT_MANIFEST).read_text(encoding="utf-8"))["files"]


def test_a_data_image_is_written_as_a_sibling_file_the_page_links_by_name(tmp_path: Path) -> None:
    result, out_dir = _exported(tmp_path, [_image(PNG_URI)])

    assert (result.files, _folder_bytes(out_dir), _manifest_files(out_dir)) == (
        (out_dir / "image-1.png", out_dir / "page.md"),
        {
            EXPORT_MANIFEST: (out_dir / EXPORT_MANIFEST).read_bytes(),
            "image-1.png": PNG_BYTES,
            "page.md": b"# Test Report\n\n![Aisle 12](image-1.png)\n",
        },
        ["image-1.png", "page.md"],
    )


def test_each_image_is_named_by_its_order_and_takes_the_extension_of_its_media_type(tmp_path: Path) -> None:
    blocks = [_image(PNG_URI), _image(JPEG_URI, "Dock"), _image(PERCENT_ENCODED_SVG_URI, "Plan")]

    _, out_dir = _exported(tmp_path, blocks)

    assert (_folder_bytes(out_dir)["page.md"], _manifest_files(out_dir)) == (
        b"# Test Report\n\n![Aisle 12](image-1.png)\n\n![Dock](image-2.jpg)\n\n![Plan](image-3.svg)\n",
        ["image-1.png", "image-2.jpg", "image-3.svg", "page.md"],
    )
    assert (out_dir / "image-3.svg").read_text(encoding="utf-8") == SVG_TEXT


def test_the_same_data_uri_used_twice_is_one_file(tmp_path: Path) -> None:
    _, out_dir = _exported(tmp_path, [_image(PNG_URI), _image(PNG_URI, "Again")])

    assert (_folder_bytes(out_dir)["page.md"], _manifest_files(out_dir)) == (
        b"# Test Report\n\n![Aisle 12](image-1.png)\n\n![Again](image-1.png)\n",
        ["image-1.png", "page.md"],
    )


def test_an_image_inside_a_toggle_and_a_tab_is_written_too(tmp_path: Path) -> None:
    blocks = [
        {"type": "toggle", "title": "Photos", "blocks": [_image(PNG_URI)]},
        {
            "type": "tabs",
            "tabs": [
                {"label": "Dock", "blocks": [_image(JPEG_URI, "Dock")]},
                {"label": "Notes", "blocks": [{"type": "text", "body": "Overflow bins."}]},
            ],
        },
    ]

    _, out_dir = _exported(tmp_path, blocks)

    assert _manifest_files(out_dir) == ["image-1.png", "image-2.jpg", "page.md"]


def test_a_web_image_writes_no_file(tmp_path: Path) -> None:
    _, out_dir = _exported(tmp_path, [_image("https://example.com/aisle.png")])

    assert _manifest_files(out_dir) == ["page.md"]


def test_render_export_hands_back_the_image_files_beside_the_page() -> None:
    report = parse_report(make_report(blocks=[_image(PNG_URI)]))

    rendered = render_export(report, "markdown")

    assert (dict(rendered.pages), dict(rendered.files)) == (
        {"page.md": "# Test Report\n\n![Aisle 12](image-1.png)\n"},
        {"image-1.png": PNG_BYTES},
    )


def test_a_re_export_without_the_image_removes_the_file_an_earlier_export_wrote(tmp_path: Path) -> None:
    _, out_dir = _exported(tmp_path, [_image(PNG_URI)])
    report = load_report(write_report(tmp_path, make_report(blocks=[{"type": "text", "body": "No image."}])))

    export_markdown(report, out_dir)

    assert (sorted(path.name for path in out_dir.iterdir()), _manifest_files(out_dir)) == (
        [EXPORT_MANIFEST, "page.md"],
        ["page.md"],
    )


def test_an_image_file_of_your_own_that_the_export_would_replace_stops_the_export(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "image-1.png").write_bytes(b"mine")
    report = load_report(write_report(tmp_path, make_report(blocks=[_image(PNG_URI)])))

    with pytest.raises(ReportError) as raised:
        export_markdown(report, out_dir)

    assert (str(raised.value), _folder_bytes(out_dir)) == (
        f"refusing to overwrite {out_dir / 'image-1.png'}, which is not on the {EXPORT_MANIFEST} "
        f"list of files skaldr wrote; move it away or choose another --export-dir",
        {"image-1.png": b"mine"},
    )


def test_a_file_the_manifest_lists_under_a_name_that_is_not_a_page_or_an_image_is_left_alone(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "notes.txt").write_text("mine", encoding="utf-8")
    (out_dir / EXPORT_MANIFEST).write_text(
        '{"title": "T", "files": ["notes.txt", "page.md"]}', encoding="utf-8"
    )
    report = load_report(write_report(tmp_path, make_report()))

    result = export_markdown(report, out_dir)

    assert (result.unreadable_manifest, (out_dir / "notes.txt").read_text(encoding="utf-8")) == (True, "mine")


@pytest.mark.parametrize(
    ("src", "problem"),
    [
        pytest.param(
            "data:text/html;base64,PGI+aGk8L2I+",
            "its media type 'text/html' is not a png, jpeg, gif, webp, svg+xml, avif or bmp image",
            id="html-media-type",
        ),
        pytest.param(
            "data:application/pdf;base64,AA==",
            "its media type 'application/pdf' is not a png, jpeg, gif, webp, svg+xml, avif or bmp image",
            id="pdf-media-type",
        ),
        pytest.param(
            "data:;base64,AA==",
            "its media type 'text/plain' is not a png, jpeg, gif, webp, svg+xml, avif or bmp image",
            id="no-media-type",
        ),
        pytest.param("data:image/png;base64,A", "its payload does not decode", id="truncated-base64"),
        pytest.param("data:image/png;base64,", "its payload does not decode", id="empty-payload"),
        pytest.param("data:image/png;base64", "its payload does not decode", id="no-payload-separator"),
    ],
)
def test_github_refuses_a_data_uri_it_cannot_write_as_an_image_file(src: str, problem: str) -> None:
    report = parse_report(make_report(blocks=[_image(src)]))

    with pytest.raises(ExportRejectedError) as raised:
        render_export(report, "markdown")

    assert str(raised.value) == (
        f"GitHub cannot write an image from a data: URI as a file, since {problem}, "
        f"at blocks.0.image; {GIVE_AN_IMAGE_DATA_URI}"
    )


def test_a_refused_data_uri_writes_nothing(tmp_path: Path) -> None:
    report = load_report(write_report(tmp_path, make_report(blocks=[_image("data:text/html;base64,AA==")])))
    out_dir = tmp_path / "out"

    with pytest.raises(ExportRejectedError):
        export_markdown(report, out_dir)

    assert not out_dir.exists()


@pytest.mark.parametrize("target", ["notion", "adf", "slack"])
def test_a_data_uri_the_other_targets_cannot_show_is_refused_as_an_image_from_a_data_uri(
    target: ExportTarget,
) -> None:
    report = parse_report(make_report(blocks=[_image("data:text/html;base64,AA==")]))

    with pytest.raises(ExportRejectedError) as raised:
        render_export(report, target)

    assert "cannot show an image from a data: URI" in str(raised.value)
