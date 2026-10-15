from skaldr.errors import ExportInvariantError
from skaldr.export.capabilities import PANES_FEATURES, swaps
from skaldr.export.glyphs import tab_title_led_by_its_icon
from skaldr.export.tree import Tabs, Toggle
from skaldr.export_targets import ExportTarget


def tabs_as_toggles(node: Tabs) -> tuple[Toggle, ...]:
    return tuple(
        Toggle(tab_title_led_by_its_icon(tab), heading_level=None, children=tab.children) for tab in node.tabs
    )


def tabs_swapped_for_toggles(node: Tabs, target: ExportTarget) -> tuple[Toggle, ...]:
    feature = PANES_FEATURES[node.kind]
    if not swaps(feature, target):
        raise ExportInvariantError(
            f"the capability table keeps a {feature} on {target}, "
            "but its writer has no form for it other than toggles"
        )
    return tabs_as_toggles(node)
