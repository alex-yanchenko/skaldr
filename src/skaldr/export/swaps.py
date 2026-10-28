from collections.abc import Mapping
from typing import Final, assert_never

from skaldr.errors import ExportInvariantError
from skaldr.export.capabilities import PANES_FEATURES, TARGET_SUBJECTS, Feature, OccurrenceFeature, swaps
from skaldr.export.glyphs import tab_title_led_by_its_icon
from skaldr.export.tree import Diagram, Figure, Graph, GraphKind, Media, Node, PieChart, Tabs, Toggle, XYChart
from skaldr.export_targets import ExportTarget
from skaldr.models import is_data_uri

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
    if is_data_uri(media.url):
        raise ExportInvariantError(
            f"{TARGET_SUBJECTS[target]} has no form for 'image from a data: URI'; "
            "the export check should have refused it"
        )
    return media.url


def mermaid_cannot_draw(figure: Figure) -> bool:
    return figure_feature(figure) == "chart with several series"


def swaps_the_figure(node: Diagram, target: ExportTarget) -> bool:
    return swaps(figure_feature(node.figure), target)


def figure_mermaid_draws(node: Diagram, target: ExportTarget) -> Figure:
    if mermaid_cannot_draw(node.figure):
        require_the_swap(figure_feature(node.figure), target)
    return node.figure


def data_table_swapped_in(node: Diagram, target: ExportTarget) -> tuple[Node, ...]:
    require_the_swap(figure_feature(node.figure), target)
    return node.supplement


def tabs_as_toggles(node: Tabs) -> tuple[Toggle, ...]:
    return tuple(
        Toggle(tab_title_led_by_its_icon(tab), heading_level=None, children=tab.children) for tab in node.tabs
    )


def tabs_swapped_for_toggles(node: Tabs, target: ExportTarget) -> tuple[Toggle, ...]:
    require_the_swap(PANES_FEATURES[node.kind], target)
    return tabs_as_toggles(node)
