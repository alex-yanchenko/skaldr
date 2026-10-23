from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from urllib.request import urlopen

from skaldr.export.tree import Media, Node, nested_nodes
from skaldr.models import is_data_uri

IMAGE_FILE_EXTENSIONS: Final[Mapping[str, str]] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/avif": "avif",
    "image/bmp": "bmp",
}
ACCEPTED_IMAGE_TYPES_IN_WORDS: Final = "png, jpeg, gif, webp, svg+xml, avif or bmp"
UNDECODABLE_PAYLOAD: Final = "its payload does not decode"


@dataclass(frozen=True)
class ImageFile:
    name: str
    content: bytes


@dataclass(frozen=True)
class DataImage:
    extension: str
    content: bytes


@dataclass(frozen=True)
class UnwritableDataImage:
    problem: str


def _not_an_accepted_type(media_type: str) -> str:
    return f"its media type '{media_type}' is not a {ACCEPTED_IMAGE_TYPES_IN_WORDS} image"


def read_data_image(src: str) -> DataImage | UnwritableDataImage:
    try:
        with urlopen(src) as opened:
            media_type = opened.headers.get_content_type()
            content = opened.read()
    except ValueError:
        return UnwritableDataImage(UNDECODABLE_PAYLOAD)
    extension = IMAGE_FILE_EXTENSIONS.get(media_type)
    if extension is None:
        return UnwritableDataImage(_not_an_accepted_type(media_type))
    if not content:
        return UnwritableDataImage(UNDECODABLE_PAYLOAD)
    return DataImage(extension, content)


def _data_image_sources(nodes: Sequence[Node]) -> Iterator[str]:
    for node in nodes:
        if isinstance(node, Media) and node.kind == "image" and is_data_uri(node.url):
            yield node.url
        yield from _data_image_sources(nested_nodes(node))


def data_image_files(nodes: Sequence[Node]) -> dict[str, ImageFile]:
    files: dict[str, ImageFile] = {}
    for src in _data_image_sources(nodes):
        if src in files:
            continue
        image = read_data_image(src)
        if isinstance(image, DataImage):
            files[src] = ImageFile(f"image-{len(files) + 1}.{image.extension}", image.content)
    return files
