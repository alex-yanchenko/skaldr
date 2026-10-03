import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from itertools import takewhile
from typing import Final, Literal, TypeGuard
from xml.etree.ElementTree import Element, tostring

from latex2mathml import commands
from latex2mathml.commands import MATRICES, NEWENVIRONMENT
from latex2mathml.converter import MOVABLE_LIMIT_TEXTS, OPERATORS, convert_to_element
from latex2mathml.symbols_parser import SYMBOLS
from latex2mathml.tokenizer import tokenize
from webcolors import names, normalize_hex

from skaldr.errors import ReportError

MathDisplay = Literal["inline", "block"]
NOTION_EQUATION_FENCE: Final = "$$"
ENVIRONMENT_OPENING = re.compile(r"\\begin\{([^{}]+)\}")
KNOWN_ENVIRONMENTS: Final = frozenset(command.removeprefix("\\") for command in MATRICES)
COLOUR_ATTRIBUTES: Final = frozenset({"mathcolor", "mathbackground", "border-color"})
CSS_COLOUR_KEYWORDS_BEYOND_CSS3: Final = frozenset({"rebeccapurple", "transparent", "currentcolor"})
CSS_COLOUR_NAMES: Final = frozenset(names("css3")) | CSS_COLOUR_KEYWORDS_BEYOND_CSS3
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
MATHML_ELEMENTS: Final = frozenset(
    {
        "math",
        "menclose",
        "mfrac",
        "mi",
        "mn",
        "mo",
        "mover",
        "mpadded",
        "mphantom",
        "mroot",
        "mrow",
        "mspace",
        "msqrt",
        "mstyle",
        "msub",
        "msubsup",
        "msup",
        "mtable",
        "mtd",
        "mtext",
        "mtr",
        "munder",
        "munderover",
    }
)
TOKEN_ELEMENTS: Final = frozenset({"mi", "mo", "mn"})
LETTER_COMMAND = re.compile(r"\\[a-zA-Z]+\*?")
FONT_PREFIX_NAMING_NO_COMMAND: Final = commands.MATH
# external:latex2mathml its walker ends a \root index at a literal \of that no command table holds
COMMANDS_OUTSIDE_LATEX2MATHML_TABLES: Final = frozenset({r"\of"})
COMMANDS_DEFINING_A_COMMAND: Final = frozenset(
    {commands.NEWCOMMAND, commands.DEF, commands.DECLAREMATHOPERATOR}
)
COMMANDS_TAKING_LITERAL_TEXT: Final = frozenset(
    {
        commands.CLAP,
        commands.CLASS,
        commands.COLOR,
        commands.EMPH,
        commands.FBOX,
        commands.HBOX,
        commands.HREF,
        commands.LLAP,
        commands.MBOX,
        commands.RLAP,
        commands.STYLE,
        commands.TAG,
        commands.TAGSTAR,
        commands.TEXT,
        commands.TEXTBF,
        commands.TEXTCOLOR,
        commands.TEXTIT,
        commands.TEXTMD,
        commands.TEXTNORMAL,
        commands.TEXTRM,
        commands.TEXTSF,
        commands.TEXTTT,
        commands.TEXTUP,
        commands.VERB,
    }
)


def _commands_latex2mathml_knows() -> frozenset[str]:
    names = {
        *SYMBOLS,
        *OPERATORS,
        *MOVABLE_LIMIT_TEXTS,
        *COMMANDS_OUTSIDE_LATEX2MATHML_TABLES,
        *(name for value in vars(commands).values() for name in _names_in_command_table(value)),
    }
    return frozenset(
        name for name in names if LETTER_COMMAND.fullmatch(name) and name != FONT_PREFIX_NAMING_NO_COMMAND
    )


def _names_in_command_table(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif _is_command_table(value):
        yield from (member for member in value if isinstance(member, str))


def _is_command_table(value: object) -> TypeGuard[Iterable[object]]:
    return isinstance(value, (tuple, dict))


LATEX2MATHML_COMMANDS: Final = _commands_latex2mathml_knows()


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
CONVERTER_HEX_ENTITY = re.compile(r"&#x([0-9A-Fa-f]+);")
REPLACEMENT_CHARACTER: Final = "\N{REPLACEMENT CHARACTER}"
LAST_CODE_POINT: Final = 0x10FFFF
SURROGATES: Final = range(0xD800, 0xE000)
ARABIC_NONCHARACTERS: Final = range(0xFDD0, 0xFDF0)
PLANE_END_NONCHARACTER_BITS: Final = 0xFFFE
CONTROL_CHARACTERS_A_PAGE_KEEPS: Final = frozenset({"\t", "\n"})


@cache
def mathml(expression: str, display: MathDisplay) -> str:
    _refuse_notion_equation_fence(expression)
    root = _converted(expression, display)
    tokens = tuple(tokenize(expression))
    _refuse_unknown_environment(tokens, expression)
    _refuse_unknown_command_token(tokens, expression)
    for element in root.iter():
        _decode_converter_entities(element)
        _refuse_element_outside_mathml(element, expression)
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


def _refuse_element_outside_mathml(element: Element, expression: str) -> None:
    if element.tag not in MATHML_ELEMENTS:
        raise ReportError(
            f"math expression '{expression}' produces a {element.tag} element, which is not a MathML "
            "element skaldr renders"
        )


def _refuse_attributes_outside_mathml(element: Element, expression: str) -> None:
    for name in element.attrib:
        if name not in MATHML_ATTRIBUTES:
            raise ReportError(
                f"math expression '{expression}' sets the {name} attribute, which is not a MathML attribute "
                r"skaldr renders: leave out \href, \class and \style"
            )


def _refuse_unknown_environment(tokens: Sequence[str], expression: str) -> None:
    defined = KNOWN_ENVIRONMENTS | _newly_defined_environments(tokens)
    for token in tokens:
        opening = ENVIRONMENT_OPENING.fullmatch(token)
        if opening is None:
            continue
        environment = opening.group(1)
        if environment not in defined:
            raise ReportError(
                f"math expression '{expression}' opens the {environment} environment, which latex2mathml "
                f"does not define: use one of {', '.join(sorted(KNOWN_ENVIRONMENTS))}"
            )


def _newly_defined_environments(tokens: Sequence[str]) -> frozenset[str]:
    return frozenset(
        _braced_argument(tokens[index + 1 :]) for index, token in enumerate(tokens) if token == NEWENVIRONMENT
    )


def _braced_argument(following: Sequence[str]) -> str:
    if not following or following[0] != "{":
        return "".join(following[:1])
    return "".join(takewhile(lambda token: token != "}", following[1:]))


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


def _refuse_unknown_command_token(tokens: Sequence[str], expression: str) -> None:
    known = LATEX2MATHML_COMMANDS | _newly_defined_commands(tokens)
    for index, token in enumerate(tokens):
        if index > 0 and tokens[index - 1] in COMMANDS_TAKING_LITERAL_TEXT:
            continue
        if token == commands.BACKSLASH:
            raise _unknown_command(expression, token + _first_character_after(tokens, index))
        if LETTER_COMMAND.fullmatch(token) and token not in known:
            raise _unknown_command(expression, token)


def _newly_defined_commands(tokens: Sequence[str]) -> frozenset[str]:
    return frozenset(
        _braced_argument(tokens[index + 1 :])
        for index, token in enumerate(tokens)
        if token in COMMANDS_DEFINING_A_COMMAND
    )


def _first_character_after(tokens: Sequence[str], index: int) -> str:
    following = tokens[index + 1 : index + 2]
    return following[0][:1] if following else ""


def _refuse_unknown_command(element: Element, expression: str) -> None:
    text = element.text or ""
    if element.tag in TOKEN_ELEMENTS and text.startswith("\\") and len(text) > 1:
        raise _unknown_command(expression, text)


def _unknown_command(expression: str, command: str) -> ReportError:
    return ReportError(
        f"math expression '{expression}' uses {command}, which latex2mathml does not know: check its "
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


def _decoded(text: str) -> str:
    return CONVERTER_HEX_ENTITY.sub(lambda match: _character_a_page_can_hold(int(match.group(1), 16)), text)


def _character_a_page_can_hold(code_point: int) -> str:
    if code_point > LAST_CODE_POINT or code_point in SURROGATES or _is_noncharacter(code_point):
        return REPLACEMENT_CHARACTER
    character = chr(code_point)
    if unicodedata.category(character) == "Cc" and character not in CONTROL_CHARACTERS_A_PAGE_KEEPS:
        return REPLACEMENT_CHARACTER
    return character


def _is_noncharacter(code_point: int) -> bool:
    return (
        code_point in ARABIC_NONCHARACTERS
        or code_point & PLANE_END_NONCHARACTER_BITS == PLANE_END_NONCHARACTER_BITS
    )
