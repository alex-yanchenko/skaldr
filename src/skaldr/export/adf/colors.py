from collections.abc import Mapping
from typing import Final

from skaldr.export.adf.nodes import LozengeColor, PanelType
from skaldr.export.tree import ToneName
from skaldr.models import BadgeColorLiteral

TEXT_COLOR: Final[Mapping[ToneName, str]] = {
    "neutral": "#6B778C",
    "muted": "#6B778C",
    "info": "#0052CC",
    "success": "#00875A",
    "warning": "#FF8B00",
    "danger": "#DE350B",
    "accent": "#6554C0",
    "teal": "#008DA6",
    "sky": "#00A3BF",
}
BACKGROUND_COLOR: Final[Mapping[ToneName, str]] = {
    "neutral": "#F4F5F7",
    "muted": "#F4F5F7",
    "info": "#DEEBFF",
    "success": "#E3FCEF",
    "warning": "#FFFAE6",
    "danger": "#FFEBE6",
    "accent": "#EAE6FF",
    "teal": "#E6FCFF",
    "sky": "#B3D4FF",
}
PANEL_TYPE: Final[Mapping[ToneName, PanelType]] = {
    "neutral": "note",
    "muted": "note",
    "info": "info",
    "success": "success",
    "warning": "warning",
    "danger": "error",
    "accent": "note",
    "teal": "info",
    "sky": "info",
}
BADGE_LOZENGE: Final[Mapping[BadgeColorLiteral, LozengeColor]] = {
    "slate": "neutral",
    "blue": "blue",
    "green": "green",
    "amber": "yellow",
    "red": "red",
    "violet": "purple",
    "teal": "green",
    "sky": "blue",
}
