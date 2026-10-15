from collections.abc import Mapping
from typing import Final

from typing_extensions import assert_never

from skaldr.errors import ExportInvariantError
from skaldr.export.capabilities import TARGET_SUBJECTS, Feature, OccurrenceFeature, swaps
from skaldr.export.tree import Diagram, Figure, Graph, GraphKind, Media, Node, PieChart, XYChart
from skaldr.export_targets import ExportTarget

DATA_URI_SCHEME: Final = "data:"
GRAPH_FEATURES: Final[Mapping[GraphKind, OccurrenceFeature]] = {
    "flow": "flow diagram",
    "fan": "fan diagram",
}


def figure_feature(figure: Figure) -> OccurrenceFeature:
    match figure:
        case Graph():
            return GRAPH_FEATURES[figure.kind]
        case PieChart():
            return "chart"
        case XYChart():
            return "chart with several series" if len(figure.series) > 1 else "chart"
        case _:
            assert_never(figure)


def require_the_swap(feature: Feature, target: ExportTarget) -> None:
    if not swaps(feature, target):
        raise ExportInvariantError(
            f"{TARGET_SUBJECTS[target]} has no form for '{feature}'; the export check should have refused it"
        )


def web_address_of(media: Media, target: ExportTarget) -> str:
    if media.url.startswith(DATA_URI_SCHEME):
        raise ExportInvariantError(
            f"{TARGET_SUBJECTS[target]} has no form for 'image from a data: URI'; "
            "the export check should have refused it"
        )
    return media.url


def mermaid_cannot_draw(figure: Figure) -> bool:
    return isinstance(figure, XYChart) and len(figure.series) > 1


def data_table_swapped_in(node: Diagram, target: ExportTarget) -> tuple[Node, ...]:
    require_the_swap(figure_feature(node.figure), target)
    return node.supplement
