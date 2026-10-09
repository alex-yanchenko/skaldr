import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx2

from skaldr.auth.store import JiraCredentials, require_jira
from skaldr.errors import AuthError, ConnectorError
from skaldr.export.adf import JIRA_DESCRIPTION_LIMIT, render_adf_regions
from skaldr.export.tree import LoweredDocument
from skaldr.models import Report
from skaldr.publish.connector import ContentLimit, WriteGranularity
from skaldr.publish.jira.client import JiraClient
from skaldr.publish.jira.description import as_blocks, description_length, section_text
from skaldr.publish.jira.transport import JiraTransport
from skaldr.publish_block import JiraTarget, TargetBase

DESCRIPTION_LIMIT = ContentLimit("item", JIRA_DESCRIPTION_LIMIT, "characters of ADF", description_length)


def _stored_sign_in() -> JiraCredentials:
    return require_jira().credentials


@dataclass(frozen=True)
class JiraConnector:
    sign_in: Callable[[], JiraCredentials] = _stored_sign_in
    http_transport: httpx2.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep

    @property
    def target_type(self) -> type[TargetBase]:
        return JiraTarget

    @property
    def limits(self) -> tuple[ContentLimit, ...]:
        return (DESCRIPTION_LIMIT,)

    @property
    def writes(self) -> WriteGranularity:
        return "content"

    def render_regions(self, _report: Report, page: LoweredDocument, /) -> tuple[str, ...]:
        return tuple(section_text(as_blocks(blocks)) for blocks in render_adf_regions(page))

    def existing_item_id(self, _target: TargetBase, /) -> str | None:
        return None

    def open_transport(self, _target: TargetBase, /) -> JiraTransport:
        try:
            credentials = self.sign_in()
        except AuthError as exc:
            raise ConnectorError(str(exc)) from exc
        return JiraTransport(JiraClient(credentials, transport=self.http_transport, sleep=self.sleep))
