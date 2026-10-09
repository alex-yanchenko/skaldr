from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Protocol

from skaldr.errors import ConnectorError
from skaldr.export.tree import LoweredDocument
from skaldr.models import Report
from skaldr.publish.transport import Transport
from skaldr.publish_block import PUBLISH_TARGET_TYPES, TargetBase
from skaldr.services import Service

LimitScope = Literal["section", "item"]


@dataclass(frozen=True)
class ContentLimit:
    scope: LimitScope
    maximum: int
    unit: str
    measure: Callable[[str], int] = len


class Connector(Protocol):
    @property
    def target_type(self) -> type[TargetBase]: ...

    @property
    def limits(self) -> tuple[ContentLimit, ...]: ...

    def render_regions(self, report: Report, page: LoweredDocument, /) -> tuple[str, ...]: ...

    def existing_item_id(self, target: TargetBase, /) -> str | None: ...

    def open_transport(self, target: TargetBase, /) -> Transport: ...


def _service_of_a_listed_target(target_type: type[TargetBase]) -> Service:
    if target_type not in PUBLISH_TARGET_TYPES:
        listed = ", ".join(listed_type.__name__ for listed_type in PUBLISH_TARGET_TYPES)
        raise ConnectorError(
            f"a connector publishes {target_type.__name__}, which is not one of the publish block's "
            f"targets ({listed})"
        )
    return target_type.service()


class ConnectorRegistry:
    def __init__(self, connectors: Iterable[Connector]) -> None:
        by_service: dict[Service, Connector] = {}
        for connector in connectors:
            service = _service_of_a_listed_target(connector.target_type)
            if service in by_service:
                raise ConnectorError(f"two connectors publish to {service}")
            by_service[service] = connector
        self._by_service: Mapping[Service, Connector] = MappingProxyType(by_service)

    def for_service(self, service: Service) -> Connector:
        connector = self._by_service.get(service)
        if connector is None:
            raise ConnectorError(f"no connector publishes to {service}")
        return connector

    def for_target(self, target: TargetBase) -> Connector:
        return self.for_service(target.service())
