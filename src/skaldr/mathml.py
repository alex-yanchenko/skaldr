import re
from functools import cache
from typing import Final, Literal
from xml.etree.ElementTree import Element, tostring

from latex2mathml.converter import convert_to_element

from skaldr.errors import ReportError

MathDisplay = Literal["inline", "block"]
NOTION_EQUATION_FENCE: Final = "$$"
MATHML_ATTRIBUTES: Final = frozenset(
    {
        "accent",
        "border-color",
        "columnalign",
        "columnlines",
        "columnspacing",
        "depth",
        "display",
        "displaystyle",
        "fence",
        "form",
        "height",
        "largeop",
        "linebreak",
        "linethickness",
        "lspace",
        "mathbackground",
        "mathcolor",
        "mathsize",
        "mathvariant",
        "maxsize",
        "minsize",
        "movablelimits",
        "notation",
        "rowlines",
        "rowspacing",
        "rspace",
        "scriptlevel",
        "separator",
        "stretchy",
        "voffset",
        "width",
        "xmlns",
    }
)
TOKEN_ELEMENTS: Final = frozenset({"mi", "mo", "mn"})
FRACTION_PARTS: Final = 2
CONVERTER_HEX_ENTITY = re.compile(r"&#x([0-9A-Fa-f]+);")


@cache
def mathml(expression: str, display: MathDisplay) -> str:
    _refuse_notion_equation_fence(expression)
    root = _converted(expression, display)
    for element in root.iter():
        _decode_converter_entities(element)
        _refuse_attributes_outside_mathml(element, expression)
        _refuse_unknown_command(element, expression)
        _refuse_fraction_with_one_part(element, expression)
    return tostring(root, encoding="unicode")


def refuse_invalid_math(expression: str, display: MathDisplay) -> None:
    mathml(expression, display)


def _converted(expression: str, display: MathDisplay) -> Element:
    try:
        return convert_to_element(expression, display=display)
    except Exception as error:
        raise ReportError(
            f"invalid math expression '{expression}': latex2mathml cannot convert it ({type(error).__name__})"
        ) from error


def _refuse_notion_equation_fence(expression: str) -> None:
    if NOTION_EQUATION_FENCE in expression:
        raise ReportError(
            f"math expression '{expression}' holds $$, which ends a Notion equation early: "
            r"write \$\$ for literal dollars"
        )


def _refuse_attributes_outside_mathml(element: Element, expression: str) -> None:
    for name in element.attrib:
        if name not in MATHML_ATTRIBUTES:
            raise ReportError(
                f"math expression '{expression}' sets the {name} attribute, which is not a MathML attribute "
                r"skaldr renders: leave out \href, \class and \style"
            )


def _refuse_unknown_command(element: Element, expression: str) -> None:
    text = element.text or ""
    if element.tag in TOKEN_ELEMENTS and text.startswith("\\") and len(text) > 1:
        raise ReportError(
            f"math expression '{expression}' uses {text}, which latex2mathml does not know: check its "
            r"spelling, or write \text{...} for literal text"
        )


def _refuse_fraction_with_one_part(element: Element, expression: str) -> None:
    if element.tag == "mfrac" and len(element) < FRACTION_PARTS:
        raise ReportError(
            f"math expression '{expression}' has a fraction with one part: \\frac, \\dfrac, \\cfrac and "
            r"\binom each take two, as in \frac{a}{b}"
        )


def _decode_converter_entities(element: Element) -> None:
    element.attrib = {name: _decoded(value) for name, value in element.attrib.items()}
    if element.text:
        element.text = _decoded(element.text)
    if element.tail:
        element.tail = _decoded(element.tail)


def _decoded(text: str) -> str:
    return CONVERTER_HEX_ENTITY.sub(lambda match: chr(int(match.group(1), 16)), text)
