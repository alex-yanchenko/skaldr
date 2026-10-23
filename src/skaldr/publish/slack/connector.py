import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx2

from skaldr.auth.store import SlackCredentials, require_slack_for_a_target
from skaldr.errors import AuthError, ConnectorError
from skaldr.export.slack import SLACK_CANVAS_CHARACTER_LIMIT, render_slack_regions
from skaldr.export.tree import LoweredDocument
from skaldr.export_targets import ExportTarget
from skaldr.models import Report, Section
from skaldr.publish.connector import NO_SECTION_DEFAULTS, ContentLimit, SectionDefaults, WriteGranularity
from skaldr.publish.slack.api import SlackApi, Sleep
from skaldr.publish.slack.transport import SlackTransport, Warn, warn_on_stderr
from skaldr.publish_block import SlackTarget, TargetBase

CANVAS_LIMIT = ContentLimit("item", SLACK_CANVAS_CHARACTER_LIMIT, "characters of canvas Markdown")


def _stored_sign_in(workspace: str | None) -> SlackCredentials:
    return require_slack_for_a_target(workspace).credentials


@dataclass(frozen=True)
class SlackConnector:
    sign_in: Callable[[str | None], SlackCredentials] = _stored_sign_in
    http: httpx2.BaseTransport | None = None
    sleep: Sleep = time.sleep
    warn: Warn = warn_on_stderr
    target_type: type[TargetBase] = SlackTarget
    limits: tuple[ContentLimit, ...] = (CANVAS_LIMIT,)
    writes: WriteGranularity = "section"
    carries_look: bool = False
    writes_look_as_words: bool = True
    export_target: ExportTarget = "slack"

    def render_regions(self, _report: Report, page: LoweredDocument, /) -> tuple[str, ...]:
        return render_slack_regions(page)

    def section_defaults(
        self, _report: Report, _section: Section, _source_index: int, _target: TargetBase, /
    ) -> SectionDefaults:
        return NO_SECTION_DEFAULTS

    def existing_item_id(self, target: TargetBase, /) -> str | None:
        return target.where.canvas if isinstance(target, SlackTarget) else None

    def open_transport(self, target: TargetBase, /) -> SlackTransport:
        if not isinstance(target, SlackTarget):
            raise ConnectorError(f"the Slack connector cannot publish to {target.place_label()}")
        try:
            credentials = self.sign_in(target.where.workspace)
        except AuthError as exc:
            raise ConnectorError(str(exc)) from exc
        return SlackTransport(SlackApi(credentials, transport=self.http, sleep=self.sleep), warn=self.warn)
