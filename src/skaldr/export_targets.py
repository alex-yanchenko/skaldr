from collections.abc import Mapping
from typing import Final, Literal, get_args

from skaldr.services import NotionService, Service

SlackTarget = Literal["slack"]
ExportTarget = Literal[NotionService, "markdown", "adf", SlackTarget]
EXPORT_TARGETS: Final[tuple[ExportTarget, ...]] = get_args(ExportTarget)
SLACK_TARGET: Final[SlackTarget] = get_args(SlackTarget)[0]
PUBLISHED_AS: Final[Mapping[Service, ExportTarget]] = {"notion": "notion", "jira": "adf"}
