from functools import cache
from html import unescape
from typing import Final, Literal
from xml.etree.ElementTree import Element, tostring

from latex2mathml.converter import convert_to_element

from skaldr.errors import ReportError

MathDisplay = Literal["inline", "block"]
PAGE_LEVEL_ATTRIBUTES: Final = frozenset({"href", "class", "style", "id"})


@cache
def mathml(expression: str, display: MathDisplay) -> str:
    try:
        root = convert_to_element(expression, display=display)
    except Exception as error:
        raise ReportError(
            f"invalid math expression '{expression}': latex2mathml cannot convert it ({type(error).__name__})"
        ) from None
    for element in root.iter():
        _refuse_page_level_attributes(element, expression)
        _decode_entities(element)
    return tostring(root, encoding="unicode")


def refuse_invalid_math(expression: str, display: MathDisplay) -> None:
    mathml(expression, display)


def _refuse_page_level_attributes(element: Element, expression: str) -> None:
    for name in element.attrib:
        if name in PAGE_LEVEL_ATTRIBUTES or name.startswith("on"):
            raise ReportError(
                f"math expression '{expression}' sets the {name} attribute, which skaldr does not render: "
                r"leave out \href, \class and \style"
            )


def _decode_entities(element: Element) -> None:
    element.attrib = {name: unescape(value) for name, value in element.attrib.items()}
    if element.text:
        element.text = unescape(element.text)
    if element.tail:
        element.tail = unescape(element.tail)
