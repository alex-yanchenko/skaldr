from skaldr.export.glyphs import tab_title_led_by_its_icon
from skaldr.export.tree import Tabs, Toggle


def tabs_as_toggles(node: Tabs) -> tuple[Toggle, ...]:
    return tuple(
        Toggle(tab_title_led_by_its_icon(tab), heading_level=None, children=tab.children) for tab in node.tabs
    )
