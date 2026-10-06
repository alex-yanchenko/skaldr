from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Protocol

from skaldr.errors import ConnectorError
from skaldr.publish_block import PUBLISH_TARGET_TYPES, TargetBase
from skaldr.services import Service


class Connector(Protocol):
    @property
    def target_type(self) -> type[TargetBase]: ...


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

    def for_target(self, target: TargetBase) -> Connector:
        service = target.service()
        connector = self._by_service.get(service)
        if connector is None:
            raise ConnectorError(f"no connector publishes to {service}")
        return connector
