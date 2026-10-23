import base64
import string
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote_to_bytes
from xml.etree import ElementTree

from skaldr.export.tree import Media, Node, nested_nodes
from skaldr.models import DATA_URI_SCHEME, is_data_uri

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
NOT_A_DATA_URI: Final = "it is not a data: URI"
UNDECODABLE_PAYLOAD: Final = "its payload does not decode"
DEFAULT_MEDIA_TYPE: Final = "text/plain"
BASE64_FLAG: Final = "base64"
SVG_ROOT_TAGS: Final = frozenset({"svg", "{http://www.w3.org/2000/svg}svg"})
WHITESPACE_YAML_MAY_FOLD_IN: Final = {ord(character): None for character in string.whitespace}


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


def _is_svg(content: bytes) -> bool:
    try:
        return ElementTree.fromstring(content).tag in SVG_ROOT_TAGS
    except ElementTree.ParseError:
        return False


def _is_webp(content: bytes) -> bool:
    return content[:4] == b"RIFF" and content[8:12] == b"WEBP"


def _is_avif(content: bytes) -> bool:
    return content[4:8] == b"ftyp" and content[8:12] in (b"avif", b"avis")


IMAGE_SIGNATURES: Final[Mapping[str, Callable[[bytes], bool]]] = {
    "image/png": lambda content: content.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda content: content.startswith(b"\xff\xd8\xff"),
    "image/gif": lambda content: content.startswith((b"GIF87a", b"GIF89a")),
    "image/webp": _is_webp,
    "image/svg+xml": _is_svg,
    "image/avif": _is_avif,
    "image/bmp": lambda content: content.startswith(b"BM"),
}


def _not_an_accepted_type(media_type: str) -> str:
    return f"its media type '{media_type}' is not a {ACCEPTED_IMAGE_TYPES_IN_WORDS} image"


def _decoded_payload(parameters: Sequence[str], payload: str) -> bytes:
    if parameters[-1].strip().lower() == BASE64_FLAG:
        return base64.b64decode(payload.translate(WHITESPACE_YAML_MAY_FOLD_IN), validate=True)
    return unquote_to_bytes(payload)


def read_data_image(src: str) -> DataImage | UnwritableDataImage:
    if not is_data_uri(src):
        return UnwritableDataImage(NOT_A_DATA_URI)
    head, comma, payload = src[len(DATA_URI_SCHEME) :].partition(",")
    if not comma:
        return UnwritableDataImage(UNDECODABLE_PAYLOAD)
    parameters = head.split(";")
    media_type = parameters[0].strip().lower() or DEFAULT_MEDIA_TYPE
    extension = IMAGE_FILE_EXTENSIONS.get(media_type)
    if extension is None:
        return UnwritableDataImage(_not_an_accepted_type(media_type))
    try:
        content = _decoded_payload(parameters, payload)
    except ValueError:
        return UnwritableDataImage(UNDECODABLE_PAYLOAD)
    if not content:
        return UnwritableDataImage(UNDECODABLE_PAYLOAD)
    if not IMAGE_SIGNATURES[media_type](content):
        return UnwritableDataImage(f"its payload is not a valid {media_type}")
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
