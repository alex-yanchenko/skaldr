import time
from dataclasses import dataclass, field

import httpx2

from skaldr.auth.notion import NotionSession
from skaldr.auth.store import require_notion_for_a_target
from skaldr.export.budget import json_string_bytes
from skaldr.export.notion import notion_block_count, render_notion_regions
from skaldr.export.tree import LoweredDocument
from skaldr.models import Report
from skaldr.publish.connector import ContentLimit, WriteGranularity
from skaldr.publish.notion.api import NotionApi, Sleep
from skaldr.publish.notion.transport import SECTION_BLOCKS, SECTION_JSON_BYTES, NotionTransport
from skaldr.publish_block import NotionTarget, TargetBase, notion_page_id

NOTION_LIMITS = (
    ContentLimit("section", SECTION_BLOCKS, "Notion blocks", notion_block_count),
    ContentLimit("section", SECTION_JSON_BYTES, "bytes of JSON", json_string_bytes),
)


class _SignedInOnFirstUse:
    def __init__(self, http: httpx2.BaseTransport | None, workspace: str | None) -> None:
        self._http = http
        self._workspace = workspace
        self._session: NotionSession | None = None

    def _signed_in(self) -> NotionSession:
        if self._session is None:
            self._session = NotionSession(require_notion_for_a_target(self._workspace), transport=self._http)
        return self._session

    @property
    def access_token(self) -> str:
        return self._signed_in().access_token

    def renew(self) -> None:
        self._signed_in().renew()


@dataclass(frozen=True)
class NotionConnector:
    http: httpx2.BaseTransport | None = None
    sleep: Sleep = field(default=time.sleep)
    target_type: type[TargetBase] = NotionTarget
    limits: tuple[ContentLimit, ...] = NOTION_LIMITS
    writes: WriteGranularity = "section"

    def render_regions(self, report: Report, page: LoweredDocument, /) -> tuple[str, ...]:
        return render_notion_regions(page, report.meta.notion_width)

    def existing_item_id(self, target: TargetBase, /) -> str | None:
        if isinstance(target, NotionTarget) and target.where.page is not None:
            return notion_page_id(target.where.page)
        return None

    def open_transport(self, target: TargetBase, /) -> NotionTransport:
        workspace = target.where.workspace if isinstance(target, NotionTarget) else None
        tokens = _SignedInOnFirstUse(self.http, workspace)
        return NotionTransport(NotionApi(tokens, transport=self.http, sleep=self.sleep))
