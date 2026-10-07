import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, get_args

import pytest

from skaldr.errors import ConnectorError
from skaldr.export import ExportTarget
from skaldr.publish import ConnectorRegistry
from skaldr.publish_block import PUBLISH_TARGET_TYPES, JiraTarget, NotionTarget, TargetBase
from skaldr.services import SERVICES
from tests.factories import make_jira_target, make_notion_target


@dataclass(frozen=True)
class StubConnector:
    target_type: type[TargetBase]


class UnlistedNotionTarget(NotionTarget):
    pass


class TwoServiceTarget(TargetBase):
    to: Literal["notion", "jira"]


class UnknownServiceTarget(TargetBase):
    to: Literal["chat"]


class FreeTextTarget(TargetBase):
    to: str


def test_the_service_vocabulary_names_notion_and_jira() -> None:
    assert SERVICES == ("notion", "jira")


def test_each_service_has_one_publish_block_target_in_vocabulary_order() -> None:
    assert [target_type.service() for target_type in PUBLISH_TARGET_TYPES] == list(SERVICES)


@pytest.mark.parametrize(
    "target_type",
    [TargetBase, TwoServiceTarget, UnknownServiceTarget, FreeTextTarget],
    ids=["no-to", "two-services", "unknown-service", "free-text"],
)
def test_a_target_whose_to_names_no_single_service_is_refused(target_type: type[TargetBase]) -> None:
    expected = (
        f"{target_type.__name__} names no service: its `to` field must be a Literal of one of notion, jira"
    )

    with pytest.raises(TypeError, match=f"^{re.escape(expected)}$"):
        target_type.service()


def test_the_export_flavors_stay_notion_and_markdown() -> None:
    assert get_args(ExportTarget) == ("notion", "markdown")


@pytest.mark.parametrize(
    ("target_type", "authored"),
    [(NotionTarget, make_notion_target), (JiraTarget, make_jira_target)],
    ids=["notion", "jira"],
)
def test_a_target_finds_the_connector_registered_for_its_service(
    target_type: type[TargetBase], authored: Callable[[], dict[str, Any]]
) -> None:
    connectors = {listed_type: StubConnector(listed_type) for listed_type in PUBLISH_TARGET_TYPES}
    registry = ConnectorRegistry(connectors.values())

    assert registry.for_target(target_type.model_validate(authored())) is connectors[target_type]


def test_a_target_whose_service_has_no_connector_is_refused() -> None:
    registry = ConnectorRegistry([StubConnector(NotionTarget)])

    with pytest.raises(ConnectorError, match=r"^no connector publishes to jira$"):
        registry.for_target(JiraTarget.model_validate(make_jira_target()))


def test_two_connectors_for_one_service_are_refused() -> None:
    with pytest.raises(ConnectorError, match=r"^two connectors publish to notion$"):
        ConnectorRegistry([StubConnector(NotionTarget), StubConnector(NotionTarget)])


def test_a_connector_for_a_target_the_publish_block_does_not_list_is_refused() -> None:
    expected = (
        "a connector publishes UnlistedNotionTarget, which is not one of the publish block's targets "
        "(NotionTarget, JiraTarget)"
    )

    with pytest.raises(ConnectorError, match=f"^{re.escape(expected)}$"):
        ConnectorRegistry([StubConnector(UnlistedNotionTarget)])
