import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx2

from skaldr.auth.store import JiraCredentials, load_jira, require_jira, stored_jira_sign_ins
from skaldr.errors import AuthError, ConnectorError, SeveralSignInsError
from skaldr.export.adf import JIRA_DESCRIPTION_LIMIT, render_adf_regions
from skaldr.export.tree import LoweredDocument
from skaldr.models import Report
from skaldr.publish.connector import ContentLimit, WriteGranularity
from skaldr.publish.jira.client import JiraClient
from skaldr.publish.jira.description import as_blocks, description_length, section_text
from skaldr.publish.jira.transport import JiraTransport
from skaldr.publish_block import JiraTarget, TargetBase
from skaldr.publish_block.target import JsonFields

DESCRIPTION_LIMIT = ContentLimit("item", JIRA_DESCRIPTION_LIMIT, "characters of ADF", description_length)


def _not_signed_in_message(site: str) -> str:
    signed_in = [entry.identifier for entry in stored_jira_sign_ins() if entry.identifier is not None]
    if not signed_in:
        return f"Not signed in to Jira at {site}; run `skaldr auth jira`"
    return (
        f"Not signed in to Jira at {site}; signed in to {', '.join(signed_in)}; "
        "run `skaldr auth jira` to add it"
    )


def _stored_sign_in(site: str | None) -> JiraCredentials:
    try:
        found = load_jira(site)
    except SeveralSignInsError as exc:
        raise AuthError(f"{exc} with `site` in the target's `where`") from exc
    if found is not None:
        return found.credentials
    if site is None:
        return require_jira().credentials
    raise AuthError(_not_signed_in_message(site))


@dataclass(frozen=True)
class JiraConnector:
    sign_in: Callable[[str | None], JiraCredentials] = _stored_sign_in
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

    def open_transport(self, target: TargetBase, /) -> JiraTransport:
        try:
            credentials = self.sign_in(_site_of(target))
        except AuthError as exc:
            raise ConnectorError(str(exc)) from exc
        client = JiraClient(credentials, transport=self.http_transport, sleep=self.sleep)
        return JiraTransport(client, _field_shapes(target))


def _site_of(target: TargetBase) -> str | None:
    return target.where.site if isinstance(target, JiraTarget) else None


def _field_shapes(target: TargetBase) -> JsonFields:
    shapes = dict(target.where_fields())
    for override in target.overrides.values():
        shapes.update(override.fields)
    return shapes
