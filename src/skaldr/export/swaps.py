from skaldr.export.glyphs import tab_icon
from skaldr.export.runs import ExportRich
from skaldr.export.tree import Tab, Tabs, Toggle
from skaldr.richtext import Plain


def _title_led_by_its_icon(tab: Tab) -> ExportRich:
    icon = tab_icon(tab.tone)
    if icon is None:
        return tab.title
    return (Plain(f"{icon} "), *tab.title) if tab.title else (Plain(icon),)


def tabs_as_toggles(node: Tabs) -> tuple[Toggle, ...]:
    return tuple(
        Toggle(_title_led_by_its_icon(tab), heading_level=None, children=tab.children) for tab in node.tabs
    )
