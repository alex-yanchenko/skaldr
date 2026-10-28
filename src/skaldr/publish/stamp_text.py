import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, assert_never

from markdown_it import MarkdownIt
from markdown_it.token import Token

from skaldr.export.markup import encode_url
from skaldr.patterns import SLUG_PATTERN
from skaldr.publish.transport import ShownLink, Stamp
from skaldr.publish_block import notion_page_id, slack_canvas_id
from skaldr.services import SERVICE_NAMES, SERVICES_BY_NAME, Service
from skaldr.typed_links import issue_key_in_url

STAMP_WORDS: Final = "Published with skaldr from document"
LINK_GROUP_SEPARATOR: Final = " · "
LINK_SEPARATOR: Final = ", "
SERVICE_NAME_END: Final = " "
STAMP_LINKS_PARSER: Final = MarkdownIt("commonmark")
Escapes = Mapping[int, str]


def stamp_pattern(trailer: str) -> re.Pattern[str]:
    trailing = rf"(?: {re.escape(trailer)})?" if trailer else ""
    return re.compile(
        rf"{STAMP_WORDS} ({SLUG_PATTERN})(?:, section ({SLUG_PATTERN}))?"
        rf"(?:{LINK_GROUP_SEPARATOR}((?:{'|'.join(SERVICES_BY_NAME)}){SERVICE_NAME_END}.*?))?"
        rf"{trailing}"
    )


def _by_service(links: Sequence[ShownLink]) -> dict[Service, list[ShownLink]]:
    grouped: defaultdict[Service, list[ShownLink]] = defaultdict(list[ShownLink])
    for link in links:
        grouped[link.service].append(link)
    return grouped


def _link_text(link: ShownLink, escapes: Escapes) -> str:
    return f"[{link.title.translate(escapes)}]({encode_url(link.url)})"


def _links_text(links: Sequence[ShownLink], escapes: Escapes) -> str:
    return "".join(
        f"{LINK_GROUP_SEPARATOR}{SERVICE_NAMES[service]}{SERVICE_NAME_END}"
        f"{LINK_SEPARATOR.join(_link_text(link, escapes) for link in group)}"
        for service, group in _by_service(links).items()
    )


def stamp_text(stamp: Stamp, links: Sequence[ShownLink], escapes: Escapes) -> str:
    section = "" if stamp.section_id is None else f", section {stamp.section_id}"
    return f"{STAMP_WORDS} {stamp.doc_id}{section}{_links_text(links, escapes)}"


def parsed_stamp(line: str, pattern: re.Pattern[str]) -> Stamp | None:
    found = pattern.fullmatch(line.strip())
    return None if found is None else Stamp(found.group(1), found.group(2))


def linked_item_id(service: Service, url: str) -> str:
    match service:
        case "notion":
            found = notion_page_id(url)
        case "jira":
            found = issue_key_in_url(url)
        case "slack":
            found = slack_canvas_id(url)
        case _:
            assert_never(service)
    return url if found is None else found


def _service_opened_by(text: str) -> Service | None:
    return SERVICES_BY_NAME.get(text.removeprefix(LINK_GROUP_SEPARATOR).removesuffix(SERVICE_NAME_END))


@dataclass
class _LinkReading:
    service: Service | None = None
    url: str | None = None
    title: list[str] = field(default_factory=list[str])
    links: list[ShownLink] = field(default_factory=list[ShownLink])

    def read_token(self, token: Token) -> None:
        if token.type == "link_open":
            self.url, self.title = str(token.attrGet("href") or ""), []
        elif token.type == "link_close":
            if self.service is not None and self.url is not None:
                item_id = linked_item_id(self.service, self.url)
                title = "".join(self.title)
                self.links.append(ShownLink(service=self.service, item_id=item_id, url=self.url, title=title))
            self.url = None
        elif self.url is not None:
            self.title.append(token.content)
        elif token.type == "text":
            self.service = _service_opened_by(token.content) or self.service


def parsed_stamp_links(line: str, pattern: re.Pattern[str]) -> tuple[ShownLink, ...]:
    found = pattern.fullmatch(line.strip())
    if found is None or found.group(3) is None:
        return ()
    reading = _LinkReading()
    for inline in STAMP_LINKS_PARSER.parseInline(found.group(3)):
        for token in inline.children or []:
            reading.read_token(token)
    return tuple(reading.links)
