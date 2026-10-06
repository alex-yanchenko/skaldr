import re
from dataclasses import dataclass
from typing import get_args

import pytest

from skaldr.errors import ConnectorError
from skaldr.export import ExportTarget
from skaldr.publish import Connector, ConnectorRegistry
from skaldr.publish_block import PUBLISH_TARGET_TYPES, JiraTarget, NotionTarget, TargetBase
from skaldr.services import SERVICES
from tests.factories import make_jira_target, make_notion_target


@dataclass(frozen=True)
class StubConnector:
    target_type: type[TargetBase]


class UnlistedNotionTarget(NotionTarget):
    pass


NOTION_CONNECTOR = StubConnector(NotionTarget)
JIRA_CONNECTOR = StubConnector(JiraTarget)
NOTION_TARGET = NotionTarget.model_validate(make_notion_target())
JIRA_TARGET = JiraTarget.model_validate(make_jira_target())


def test_the_service_vocabulary_names_notion_and_jira() -> None:
    assert SERVICES == ("notion", "jira")


def test_each_service_has_one_publish_block_target_in_vocabulary_order() -> None:
    assert [target_type.service() for target_type in PUBLISH_TARGET_TYPES] == list(SERVICES)


def test_the_export_flavors_stay_notion_and_markdown() -> None:
    assert get_args(ExportTarget) == ("notion", "markdown")


@pytest.mark.parametrize(
    ("target", "connector"),
    [(NOTION_TARGET, NOTION_CONNECTOR), (JIRA_TARGET, JIRA_CONNECTOR)],
    ids=["notion", "jira"],
)
def test_a_target_finds_the_connector_registered_for_its_service(
    target: TargetBase, connector: Connector
) -> None:
    registry = ConnectorRegistry([NOTION_CONNECTOR, JIRA_CONNECTOR])

    assert registry.for_target(target) is connector


def test_a_target_whose_service_has_no_connector_is_refused() -> None:
    registry = ConnectorRegistry([NOTION_CONNECTOR])

    with pytest.raises(ConnectorError, match=r"^no connector publishes to jira$"):
        registry.for_target(JIRA_TARGET)


def test_two_connectors_for_one_service_are_refused() -> None:
    with pytest.raises(ConnectorError, match=r"^two connectors publish to notion$"):
        ConnectorRegistry([NOTION_CONNECTOR, StubConnector(NotionTarget)])


def test_a_connector_for_a_target_the_publish_block_does_not_list_is_refused() -> None:
    expected = (
        "a connector publishes UnlistedNotionTarget, which is not one of the publish block's targets "
        "(NotionTarget, JiraTarget)"
    )

    with pytest.raises(ConnectorError, match=f"^{re.escape(expected)}$"):
        ConnectorRegistry([StubConnector(UnlistedNotionTarget)])
