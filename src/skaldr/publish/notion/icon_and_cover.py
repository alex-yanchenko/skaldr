from typing import Final, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import JsonValue
from typing_extensions import assert_never

from skaldr.publish.content import ItemContent
from skaldr.publish.notion.responses import (
    CustomEmojiImage,
    EmojiImage,
    ExternalImage,
    NativeIconImage,
    OtherImage,
    Page,
    PageImage,
    UploadedImage,
)
from skaldr.publish.transport import FieldsWrite, Release
from skaldr.publish_block.target import JsonFields

UPLOADED_FILE: Final = "a file uploaded to Notion"

ImageSlot = Literal["icon", "cover"]


def _uploaded_file_text(image: UploadedImage) -> str:
    if image.file is None:
        return UPLOADED_FILE
    address = urlsplit(image.file.url)
    return f"{UPLOADED_FILE} ({urlunsplit((address.scheme, address.netloc, address.path, '', ''))})"


def _native_icon_text(image: NativeIconImage) -> str:
    color = f" ({image.icon.color})" if image.icon.color else ""
    return f"Notion icon {image.icon.name}{color}"


def _image_text(image: PageImage | None, slot: ImageSlot) -> str | None:
    match image:
        case None:
            return None
        case EmojiImage():
            return image.emoji
        case ExternalImage():
            return image.external.url
        case UploadedImage():
            return _uploaded_file_text(image)
        case CustomEmojiImage():
            return f"Notion custom emoji {image.custom_emoji.id}"
        case NativeIconImage():
            return _native_icon_text(image)
        case OtherImage():
            return f"a Notion {image.type} {slot}"
        case _:
            assert_never(image)


def icon_text(page: Page) -> str | None:
    return _image_text(page.icon, "icon")


def cover_text(page: Page) -> str | None:
    return _image_text(page.cover, "cover")


def _icon_request(icon: str | None) -> JsonValue:
    return None if icon is None else {"type": "emoji", "emoji": icon}


def _cover_request(cover: str | None) -> JsonValue:
    return None if cover is None else {"type": "external", "external": {"url": cover}}


def icon_and_cover_to_set(content: ItemContent) -> JsonFields:
    return {
        **({"icon": _icon_request(content.icon)} if content.icon is not None else {}),
        **({"cover": _cover_request(content.cover)} if content.cover is not None else {}),
    }


def icon_and_cover_to_change(request: FieldsWrite) -> JsonFields:
    return {
        **({"icon": _icon_request(request.icon)} if request.changes_the_icon else {}),
        **({"cover": _cover_request(request.cover)} if request.changes_the_cover else {}),
    }


def icon_and_cover_to_clear(page: Page, request: Release) -> JsonFields:
    return {
        **({"icon": None} if request.clears_icon and page.icon is not None else {}),
        **({"cover": None} if request.clears_cover and page.cover is not None else {}),
    }
