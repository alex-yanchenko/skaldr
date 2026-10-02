import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Final, Literal
from xml.etree.ElementTree import Element, tostring

from latex2mathml.commands import MATRICES
from latex2mathml.converter import convert_to_element
from latex2mathml.tokenizer import tokenize
from webcolors import names, normalize_hex

from skaldr.errors import ReportError

MathDisplay = Literal["inline", "block"]
NOTION_EQUATION_FENCE: Final = "$$"
ENVIRONMENT_OPENING: Final = r"\begin{"
KNOWN_ENVIRONMENTS: Final = frozenset(command.removeprefix("\\") for command in MATRICES)
NEW_ENVIRONMENT = re.compile(r"\\newenvironment\{([^{}]+)\}")
COLOUR_ATTRIBUTES: Final = frozenset({"mathcolor", "mathbackground", "border-color"})
CSS_COLOUR_NAMES: Final = frozenset(names("css3"))
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


@dataclass(frozen=True)
class RequiredParts:
    count: int
    missing: str


_FRACTION: Final = RequiredParts(
    2, r"a fraction missing a part: \frac, \dfrac, \cfrac and \binom each take two, as in \frac{a}{b}"
)
_STACK: Final = RequiredParts(
    2,
    r"a stacked expression missing a part: \overset, \underset and \stackrel each take two, "
    r"as in \overset{a}{b}",
)
_ROOT: Final = RequiredParts(2, r"a root missing a part: \sqrt[n]{x} takes an index and a radicand")
_SCRIPT_MISSING_A_PART: Final = (
    "a subscript or superscript missing a part: a script attaches to what comes before it, as in x_i, "
    "or to an empty {} as in {}_a"
)
_ONE_SCRIPT: Final = RequiredParts(2, _SCRIPT_MISSING_A_PART)
_TWO_SCRIPTS: Final = RequiredParts(3, _SCRIPT_MISSING_A_PART)
REQUIRED_PARTS: Final[Mapping[str, RequiredParts]] = {
    "mfrac": _FRACTION,
    "mover": _STACK,
    "munder": _STACK,
    "mroot": _ROOT,
    "msub": _ONE_SCRIPT,
    "msup": _ONE_SCRIPT,
    "msubsup": _TWO_SCRIPTS,
    "munderover": _TWO_SCRIPTS,
}
CONVERTER_HEX_ENTITY = re.compile(r"&#x[0-9A-Fa-f]+;")


@cache
def mathml(expression: str, display: MathDisplay) -> str:
    _refuse_notion_equation_fence(expression)
    root = _converted(expression, display)
    _refuse_unknown_environment(expression)
    for element in root.iter():
        _decode_converter_entities(element)
        _refuse_attributes_outside_mathml(element, expression)
        _refuse_unknown_colour(element, expression)
        _refuse_unknown_command(element, expression)
        _refuse_element_missing_a_part(element, expression)
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


def _refuse_unknown_environment(expression: str) -> None:
    defined = KNOWN_ENVIRONMENTS | frozenset(NEW_ENVIRONMENT.findall(expression))
    for token in tokenize(expression):
        if not token.startswith(ENVIRONMENT_OPENING):
            continue
        environment = token.removeprefix(ENVIRONMENT_OPENING).removesuffix("}")
        if environment not in defined:
            raise ReportError(
                f"math expression '{expression}' opens the {environment} environment, which latex2mathml "
                f"does not define: use one of {', '.join(sorted(KNOWN_ENVIRONMENTS))}"
            )


def _refuse_unknown_colour(element: Element, expression: str) -> None:
    for name, value in element.attrib.items():
        if name in COLOUR_ATTRIBUTES and not _is_css_colour(value):
            raise ReportError(
                f"math expression '{expression}' sets the colour '{value}', which is neither a CSS colour "
                "name nor a #rgb or #rrggbb value"
            )


def _is_css_colour(value: str) -> bool:
    if value.lower() in CSS_COLOUR_NAMES:
        return True
    try:
        normalize_hex(value)
    except ValueError:
        return False
    return True


def _refuse_unknown_command(element: Element, expression: str) -> None:
    text = element.text or ""
    if element.tag in TOKEN_ELEMENTS and text.startswith("\\") and len(text) > 1:
        raise ReportError(
            f"math expression '{expression}' uses {text}, which latex2mathml does not know: check its "
            r"spelling, or write \text{...} for literal text"
        )


def _refuse_element_missing_a_part(element: Element, expression: str) -> None:
    parts = REQUIRED_PARTS.get(element.tag)
    if parts is not None and len(element) < parts.count:
        raise ReportError(f"math expression '{expression}' has {parts.missing}")


def _decode_converter_entities(element: Element) -> None:
    element.attrib = {name: _decoded(value) for name, value in element.attrib.items()}
    if element.text:
        element.text = _decoded(element.text)
    if element.tail:
        element.tail = _decoded(element.tail)


def _decoded(text: str) -> str:
    return CONVERTER_HEX_ENTITY.sub(lambda match: html.unescape(match.group(0)), text)
