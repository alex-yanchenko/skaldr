from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache
from xml.etree.ElementTree import Element, SubElement

import pytest
from latex2mathml.commands import MATRICES
from latex2mathml.converter import convert_to_element
from latex2mathml.exceptions import MissingSuperScriptOrSubscriptError

from skaldr import mathml as mathml_module
from skaldr.errors import ReportError
from skaldr.mathml import LATEX2MATHML_COMMANDS, MATHML_ATTRIBUTES, MATHML_ELEMENTS, MathDisplay, mathml

MATH_OPEN = '<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">'
CONVERTER_PREFIX = "latex2mathml cannot convert it ("


@pytest.mark.parametrize(
    ("expression", "markup"),
    [
        pytest.param(
            r"\sum_{i=1}^{n} x_i",
            "<mrow><msubsup><mo>∑</mo><mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mrow><mi>n</mi></mrow>"
            "</msubsup><msub><mi>x</mi><mi>i</mi></msub></mrow>",
            id="sum-with-limits-and-a-subscript",
        ),
        pytest.param(
            r"\frac{a}{b}",
            "<mrow><mfrac><mrow><mi>a</mi></mrow><mrow><mi>b</mi></mrow></mfrac></mrow>",
            id="fraction",
        ),
        pytest.param(r"a \over b", "<mrow><mfrac><mi>a</mi><mi>b</mi></mfrac></mrow>", id="over"),
        pytest.param(
            r"\alpha + \beta",
            "<mrow><mi>\N{GREEK SMALL LETTER ALPHA}</mi><mo>+</mo>"
            "<mi>\N{GREEK SMALL LETTER BETA}</mi></mrow>",
            id="greek-letters",
        ),
        pytest.param(r"\backslash", "<mrow><mi>\\</mi></mrow>", id="backslash"),
        pytest.param(r"\setminus", "<mrow><mi>\N{REVERSE SOLIDUS OPERATOR}</mi></mrow>", id="setminus"),
        pytest.param(
            r"\{ x \}",
            '<mrow><mo stretchy="false">{</mo><mi>x</mi><mo stretchy="false">}</mo></mrow>',
            id="escaped-braces",
        ),
        pytest.param(r"a\,b", '<mrow><mi>a</mi><mspace width="0.167em" /><mi>b</mi></mrow>', id="thin-space"),
        pytest.param(r"\$", "<mrow><mi>$</mi></mrow>", id="escaped-dollar"),
        pytest.param(r"\text{\foo}", "<mrow><mtext>\\foo</mtext></mrow>", id="backslash-inside-text"),
        pytest.param(
            r"\text{\begin{foo}}",
            "<mrow><mtext>\\begin{foo</mtext><mi>}</mi></mrow>",
            id="environment-opening-inside-text",
        ),
        pytest.param("a<b", "<mrow><mi>a</mi><mo>&lt;</mo><mi>b</mi></mrow>", id="less-than-is-escaped"),
    ],
)
def test_latex_becomes_mathml(expression: str, markup: str) -> None:
    assert mathml(expression, "inline") == f"{MATH_OPEN}{markup}</math>"


@pytest.mark.parametrize("display", [pytest.param("inline", id="inline"), pytest.param("block", id="block")])
def test_the_display_mode_is_written_on_the_math_element(display: MathDisplay) -> None:
    assert mathml("x", display) == (
        f'<math xmlns="http://www.w3.org/1998/Math/MathML" display="{display}"><mrow><mi>x</mi></mrow></math>'
    )


def test_text_inside_the_expression_cannot_open_html() -> None:
    assert mathml(r"\text{</math><b>&}", "inline") == (
        f"{MATH_OPEN}<mrow><mtext>&lt;/math&gt;&lt;b&gt;&amp;</mtext></mrow></math>"
    )


@pytest.mark.parametrize(
    ("expression", "markup"),
    [
        pytest.param(r"\text{&lt;b&gt;}", "<mtext>&amp;lt;b&amp;gt;</mtext>", id="named-entities"),
        pytest.param(r"\text{&#60;}", "<mtext>&amp;#60;</mtext>", id="decimal-entity"),
        pytest.param(r"\text{&#X3C;}", "<mtext>&amp;#X3C;</mtext>", id="hex-entity-with-a-capital-x"),
        pytest.param(r"\text{&#x3C}", "<mtext>&amp;#x3C</mtext>", id="hex-entity-without-a-semicolon"),
    ],
)
def test_an_entity_the_author_typed_shows_as_typed_like_the_exports_show_it(
    expression: str, markup: str
) -> None:
    assert mathml(expression, "inline") == f"{MATH_OPEN}<mrow>{markup}</mrow></math>"


def test_a_hex_entity_the_author_typed_decodes_like_the_converters_own() -> None:
    assert mathml(r"\text{&#x3C;b}", "inline") == f"{MATH_OPEN}<mrow><mtext>&lt;b</mtext></mrow></math>"


@pytest.mark.parametrize(
    ("expression", "character"),
    [
        pytest.param(r"\unicode{x41}", "A", id="letter"),
        pytest.param(r"\unicode{x110000}", "\N{REPLACEMENT CHARACTER}", id="past-the-last-code-point"),
        pytest.param(r"\unicode{xFFFFFFFFFFFF}", "\N{REPLACEMENT CHARACTER}", id="too-large-for-a-c-int"),
        pytest.param(r"\unicode{xD800}", "\N{REPLACEMENT CHARACTER}", id="lone-surrogate"),
        pytest.param(r"\unicode{x0}", "\N{REPLACEMENT CHARACTER}", id="nul"),
        pytest.param(
            r"\unicode{x80}", "\N{REPLACEMENT CHARACTER}", id="c1-control-kept-from-the-cp1252-remap"
        ),
        pytest.param(r"\unicode{x1}", "\N{REPLACEMENT CHARACTER}", id="c0-control"),
        pytest.param(r"\unicode{xD}", "\N{REPLACEMENT CHARACTER}", id="carriage-return"),
        pytest.param(r"\unicode{x7F}", "\N{REPLACEMENT CHARACTER}", id="delete"),
        pytest.param(r"\unicode{x9F}", "\N{REPLACEMENT CHARACTER}", id="last-c1-control"),
        pytest.param(r"\unicode{xFFFE}", "\N{REPLACEMENT CHARACTER}", id="noncharacter-ending-fffe"),
        pytest.param(r"\unicode{x10FFFF}", "\N{REPLACEMENT CHARACTER}", id="noncharacter-ending-ffff"),
        pytest.param(r"\unicode{xFDD0}", "\N{REPLACEMENT CHARACTER}", id="first-arabic-noncharacter"),
        pytest.param(r"\unicode{xFDEF}", "\N{REPLACEMENT CHARACTER}", id="last-arabic-noncharacter"),
        pytest.param(r"\unicode{x9}", "\t", id="tab"),
        pytest.param(r"\unicode{xA0}", "\N{NO-BREAK SPACE}", id="first-code-point-after-the-c1-controls"),
        pytest.param(
            r"\unicode{xFDF0}",
            "\N{ARABIC LIGATURE SALLA USED AS KORANIC STOP SIGN ISOLATED FORM}",
            id="after-the-arabic-noncharacters",
        ),
        pytest.param(r"\unicode{x10FFFD}", "\U0010fffd", id="last-assignable-code-point"),
    ],
)
def test_a_unicode_code_point_decodes_and_one_no_page_can_hold_becomes_the_replacement_character(
    expression: str, character: str
) -> None:
    assert mathml(expression, "inline") == f"{MATH_OPEN}<mrow><mi>{character}</mi></mrow></math>"


def test_an_attribute_value_cannot_close_its_quotes(stub_converter: Callable[[Element], None]) -> None:
    root = Element("math")
    SubElement(root, "mspace", {"width": '1em" onload="x'})
    stub_converter(root)

    assert mathml("x", "inline") == '<math><mspace width="1em&quot; onload=&quot;x" /></math>'


KNOWN_ENVIRONMENTS = (
    "Bmatrix, Bmatrix*, Vmatrix, Vmatrix*, align, align*, array, bmatrix, bmatrix*, cases, displaylines, "
    "eqalign, eqalignno, matrix, matrix*, pmatrix, pmatrix*, smallmatrix, split, substack, vmatrix, vmatrix*"
)


@pytest.mark.parametrize(
    ("expression", "environment"),
    [
        pytest.param(r"\begin{pmatrx} a & b \end{pmatrx}", "pmatrx", id="misspelt-matrix"),
        pytest.param(r"\begin{aligned} a &= b \\ c &= d \end{aligned}", "aligned", id="aligned"),
        pytest.param(r"x = \begin{equation} y \end{equation}", "equation", id="equation"),
    ],
)
def test_an_environment_latex2mathml_does_not_define_fails_naming_it(
    expression: str, environment: str
) -> None:
    with pytest.raises(ReportError) as raised:
        mathml(expression, "block")

    assert str(raised.value) == (
        f"math expression '{expression}' opens the {environment} environment, which latex2mathml does not "
        f"define: use one of {KNOWN_ENVIRONMENTS}"
    )


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(r"\begin{matrix} a & b \\ c & d \end{matrix}", id="matrix"),
        pytest.param(r"\begin{pmatrix} a & b \end{pmatrix}", id="pmatrix"),
        pytest.param(r"\begin{bmatrix} a & b \end{bmatrix}", id="bmatrix"),
        pytest.param(r"\begin{Vmatrix*} a \end{Vmatrix*}", id="starred-matrix"),
        pytest.param(r"f(x) = \begin{cases} 1 & x > 0 \\ 0 & x \le 0 \end{cases}", id="cases"),
        pytest.param(r"\begin{array}{c|c} a & b \end{array}", id="array"),
        pytest.param(r"\begin{split} a &= b \\ &= c \end{split}", id="split"),
        pytest.param(r"\begin{align*} a &= b \end{align*}", id="starred-align"),
        pytest.param(r"\begin {smallmatrix} a \end {smallmatrix}", id="space-before-the-name"),
        pytest.param(
            r"\newenvironment{pair}{\left(}{\right)} \begin{pair} x \end{pair}", id="newenvironment"
        ),
    ],
)
def test_an_environment_latex2mathml_defines_converts(expression: str) -> None:
    assert mathml(expression, "block").startswith('<math xmlns="http://www.w3.org/1998/Math/MathML"')


@pytest.mark.parametrize(
    ("expression", "markup"),
    [
        pytest.param(
            r"\newenvironment {pair}{\left(}{\right)} \begin{pair} x \end{pair}",
            '<mrow><mo stretchy="true" fence="true" form="prefix">(</mo><mi>x</mi>'
            '<mo stretchy="true" fence="true" form="postfix">)</mo></mrow>',
            id="space-before-the-name",
        ),
        pytest.param(
            r"\newenvironment{ pair }{(}{)} \begin{pair} x \end{pair}",
            '<mrow><mo stretchy="false">(</mo><mi>x</mi><mo stretchy="false">)</mo></mrow>',
            id="spaces-around-the-name",
        ),
        pytest.param(
            r"\newenvironment{p air}{(}{)} \begin{pair} x \end{pair}",
            '<mrow><mo stretchy="false">(</mo><mi>x</mi><mo stretchy="false">)</mo></mrow>',
            id="space-inside-the-name",
        ),
    ],
)
def test_an_environment_defined_with_spaces_in_its_newenvironment_converts(
    expression: str, markup: str
) -> None:
    assert mathml(expression, "inline") == f"{MATH_OPEN}<mrow>{markup}</mrow></math>"


@pytest.mark.parametrize(
    ("expression", "colour"),
    [
        pytest.param(r"\color{simga} x", "simga", id="misspelt-name"),
        pytest.param(r"\textcolor{simga}{x}", "simga", id="text-colour"),
        pytest.param(r"\colorbox{simga}{x}", "simga", id="box-background"),
        pytest.param(r"\fcolorbox{simga}{red}{x}", "simga", id="box-border"),
        pytest.param(r"\color{#ff} x", "#ff", id="two-digit-hex"),
        pytest.param(r'\color{red" onload="x}{y}', 'red" onload="x', id="value-holding-quotes"),
        pytest.param(r"\color{red;x} y", "red;x", id="value-holding-a-declaration-end"),
        pytest.param(r"\color{red blue} x", "red blue", id="two-colours"),
        pytest.param(r"\color{var(--x)} y", "var(--x)", id="custom-property"),
        pytest.param(r"\color{url(x)} y", "url(x)", id="url"),
        pytest.param(r"\color{color()} x", "color()", id="colour-function-the-parser-raises-on"),
        pytest.param(r"\color{color( )} x", "color( )", id="spaced-colour-function-the-parser-raises-on"),
        pytest.param(r"\color{red/*x*/} y", "red/*x*/", id="css-comment"),
        pytest.param(r"\color{/*x*/red} y", "/*x*/red", id="leading-css-comment"),
        pytest.param(r"\color{rgb(1,0,0} x", "rgb(1,0,0", id="unterminated-function"),
        pytest.param(r"\color{rgb(1,0,0))} x", "rgb(1,0,0))", id="extra-closing-parenthesis"),
        pytest.param(r"\colorbox{rgb(255 0 0)}{x}", "rgb(25500)", id="box-drops-the-spaces"),
        pytest.param(
            r"\fcolorbox{oklch(0.6 0.2 30)}{red}{x}", "oklch(0.60.230)", id="box-border-drops-the-spaces"
        ),
    ],
)
def test_a_colour_css_does_not_parse_fails_naming_it(expression: str, colour: str) -> None:
    with pytest.raises(ReportError) as raised:
        mathml(expression, "block")

    assert str(raised.value) == (
        f"math expression '{expression}' sets the colour '{colour}', which is not a CSS colour: write a "
        "colour name like red, a hex value like #ff0000, or a colour function like rgb(255,0,0)"
    )


@pytest.mark.parametrize(
    ("expression", "markup"),
    [
        pytest.param(r"\color{red} x", '<mstyle mathcolor="red"><mi>x</mi></mstyle>', id="name"),
        pytest.param(
            r"\color{DarkSlateGray} x",
            '<mstyle mathcolor="DarkSlateGray"><mi>x</mi></mstyle>',
            id="mixed-case-name",
        ),
        pytest.param(r"\color{#f00} x", '<mstyle mathcolor="#f00"><mi>x</mi></mstyle>', id="short-hex"),
        pytest.param(r"\color{#00AA00} x", '<mstyle mathcolor="#00AA00"><mi>x</mi></mstyle>', id="long-hex"),
        pytest.param(
            r"\color{rebeccapurple} x",
            '<mstyle mathcolor="rebeccapurple"><mi>x</mi></mstyle>',
            id="css-colour-level-4-name",
        ),
        pytest.param(
            r"\color{transparent} x", '<mstyle mathcolor="transparent"><mi>x</mi></mstyle>', id="transparent"
        ),
        pytest.param(
            r"\color{currentColor} x",
            '<mstyle mathcolor="currentColor"><mi>x</mi></mstyle>',
            id="current-colour",
        ),
        pytest.param(
            r"\fcolorbox{navy}{#eee}{x}",
            '<mpadded mathbackground="#eee" border-color="navy"><mtext>x</mtext></mpadded>',
            id="box",
        ),
        pytest.param(
            r"\color{rgb(1,0,0)} x", '<mstyle mathcolor="rgb(1,0,0)"><mi>x</mi></mstyle>', id="rgb-function"
        ),
        pytest.param(
            r"\color{hsl(120 50% 50%)} x",
            '<mstyle mathcolor="hsl(120 50% 50%)"><mi>x</mi></mstyle>',
            id="hsl-function",
        ),
        pytest.param(
            r"\color{oklch(0.5 0.1 120)} x",
            '<mstyle mathcolor="oklch(0.5 0.1 120)"><mi>x</mi></mstyle>',
            id="colour-level-4-function",
        ),
        pytest.param(
            r"\color{#aabbccdd} x", '<mstyle mathcolor="#aabbccdd"><mi>x</mi></mstyle>', id="hex-with-alpha"
        ),
        pytest.param(
            r"\color{rgb(255 0 0 / 50%)} x",
            '<mstyle mathcolor="rgb(255 0 0 / 50%)"><mi>x</mi></mstyle>',
            id="space-and-slash-form",
        ),
        pytest.param(
            r"\colorbox{rgb(255,0,0)}{x}",
            '<mpadded mathbackground="rgb(255,0,0)"><mtext>x</mtext></mpadded>',
            id="box-with-the-comma-form",
        ),
    ],
)
def test_a_css_colour_converts(expression: str, markup: str) -> None:
    assert mathml(expression, "inline") == f"{MATH_OPEN}<mrow>{markup}</mrow></math>"


@pytest.mark.parametrize(
    ("expression", "attribute"),
    [
        pytest.param(r"\href{https://e.com}{x}", "href", id="href"),
        pytest.param(r"\class{loud}{x}", "class", id="class"),
        pytest.param(r"\style{color:red}{x}", "style", id="style"),
    ],
)
def test_an_expression_that_sets_a_page_level_attribute_fails(expression: str, attribute: str) -> None:
    with pytest.raises(ReportError) as raised:
        mathml(expression, "inline")

    assert str(raised.value) == (
        f"math expression '{expression}' sets the {attribute} attribute, which is not a MathML attribute "
        r"skaldr renders: leave out \href, \class and \style"
    )


@pytest.fixture
def stub_converter(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Element], None]]:
    def install(root: Element) -> None:
        def convert_to_element(_expression: str, display: MathDisplay) -> Element:
            assert display == "inline"
            return root

        monkeypatch.setattr(mathml_module, "convert_to_element", convert_to_element)

    mathml.cache_clear()
    yield install
    mathml.cache_clear()


def _math_with_attribute(name: str) -> Element:
    root = Element("math")
    SubElement(root, "mi", {name: "red"}).text = "x"
    return root


@pytest.mark.parametrize(
    "attribute",
    [
        pytest.param("href", id="href"),
        pytest.param("class", id="class"),
        pytest.param("style", id="style"),
        pytest.param("id", id="id"),
        pytest.param("onclick", id="onclick"),
        pytest.param("xlink:href", id="xlink-href"),
    ],
)
def test_an_attribute_outside_the_mathml_allowlist_fails(
    stub_converter: Callable[[Element], None], attribute: str
) -> None:
    stub_converter(_math_with_attribute(attribute))

    with pytest.raises(ReportError) as raised:
        mathml("x", "inline")

    assert str(raised.value) == (
        f"math expression 'x' sets the {attribute} attribute, which is not a MathML attribute skaldr "
        r"renders: leave out \href, \class and \style"
    )


@pytest.mark.parametrize("attribute", [pytest.param(name, id=name) for name in sorted(MATHML_ATTRIBUTES)])
def test_an_attribute_on_the_mathml_allowlist_passes(
    stub_converter: Callable[[Element], None], attribute: str
) -> None:
    stub_converter(_math_with_attribute(attribute))

    assert mathml("x", "inline") == f'<math><mi {attribute}="red">x</mi></math>'


@pytest.mark.parametrize(
    "tag",
    [
        pytest.param("semantics", id="semantics"),
        pytest.param("annotation-xml", id="annotation-xml"),
        pytest.param("mglyph", id="mglyph"),
        pytest.param("script", id="script"),
        pytest.param("svg", id="svg"),
    ],
)
def test_an_element_outside_the_mathml_allowlist_fails(
    stub_converter: Callable[[Element], None], tag: str
) -> None:
    root = Element("math")
    SubElement(root, tag).text = "x"
    stub_converter(root)

    with pytest.raises(ReportError) as raised:
        mathml("x", "inline")

    assert str(raised.value) == (
        f"math expression 'x' produces a {tag} element, which is not a MathML element skaldr renders"
    )


@pytest.mark.parametrize("tag", [pytest.param(name, id=name) for name in sorted(MATHML_ELEMENTS)])
def test_an_element_on_the_mathml_allowlist_passes(
    stub_converter: Callable[[Element], None], tag: str
) -> None:
    root = Element("math")
    element = SubElement(root, tag)
    for letter in "abc":
        SubElement(element, "mi").text = letter
    stub_converter(root)

    assert mathml("x", "inline") == f"<math><{tag}><mi>a</mi><mi>b</mi><mi>c</mi></{tag}></math>"


@dataclass(frozen=True)
class Emitted:
    elements: frozenset[str]
    attributes: frozenset[str]


ARGUMENT_SHAPES = (
    "{0}",
    "{0}{{a}}{{b}}{{c}}",
    "{0}{{red}}{{x}}",
    "x {0} y",
    "{0}{{1em}}{{2em}}",
    "{0}[a]{{b}}",
)
PAGE_LEVEL_ATTRIBUTES = frozenset({"class", "href", "style"})


def _every_command_and_environment_latex2mathml_converts() -> list[str]:
    environments = [environment.removeprefix("\\") for environment in MATRICES]
    return [
        *(shape.format(command) for command in sorted(LATEX2MATHML_COMMANDS) for shape in ARGUMENT_SHAPES),
        *(rf"\begin{{{name}}}{{c|c}} a & b \\ \hline c & d \end{{{name}}}" for name in environments),
        r"x_a x^b x_a^b a \\ b",
    ]


def _converted_or_none(expression: str) -> Element | None:
    try:
        return convert_to_element(expression, display="block")
    except Exception:
        return None


@cache
def _what_latex2mathml_emits() -> Emitted:
    roots = [
        root
        for expression in _every_command_and_environment_latex2mathml_converts()
        if (root := _converted_or_none(expression)) is not None
    ]
    elements = [element for root in roots for element in root.iter()]
    return Emitted(
        elements=frozenset(element.tag for element in elements),
        attributes=frozenset(name for element in elements for name in element.attrib),
    )


def test_the_element_allowlist_is_every_element_latex2mathml_emits() -> None:
    assert _what_latex2mathml_emits().elements == MATHML_ELEMENTS


def test_the_attribute_allowlist_is_every_attribute_latex2mathml_emits_but_the_page_level_ones() -> None:
    assert _what_latex2mathml_emits().attributes == MATHML_ATTRIBUTES | PAGE_LEVEL_ATTRIBUTES


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(r"\begin{array}{c|c} a & b \\ \hline c & d \end{array}", id="array-with-rules"),
        pytest.param(r"\begin{cases} a & b \\ c & d \end{cases}", id="cases"),
        pytest.param(r"\boxed{x} \cancel{y}", id="enclosures"),
        pytest.param(r"\Big( \mathbb{R} \Big)", id="sized-fences-and-a-font"),
        pytest.param(r"\binom{n}{k} \dfrac{a}{b}", id="binomial-and-display-fraction"),
        pytest.param(r"\hat{x} \mathbin{+} \hspace{1em} \raise{1em}{y}", id="accent-spacing-and-raise"),
        pytest.param(r"\fcolorbox{red}{blue}{z} \colorbox{red}{w} \Large q", id="color-boxes-and-size"),
        pytest.param(r"\lim_{x} \det A", id="limits"),
    ],
)
def test_common_commands_emit_only_allowlisted_attributes(expression: str) -> None:
    assert mathml(expression, "block").startswith('<math xmlns="http://www.w3.org/1998/Math/MathML"')


@pytest.mark.parametrize(
    ("expression", "command"),
    [
        pytest.param(r"\simga", r"\simga", id="misspelt-greek-letter"),
        pytest.param(r"x + \unknown{y}", r"\unknown", id="unknown-command-with-an-argument"),
        pytest.param(r"\operatorname{\foo}", r"\foo", id="unknown-command-in-an-operator-name"),
        pytest.param(r"\q", r"\q", id="one-letter-command"),
        pytest.param(r"x + \q", r"\q", id="one-letter-command-after-a-term"),
        pytest.param(r"\mathbbb{R}", r"\mathbbb", id="misspelt-font-on-a-letter"),
        pytest.param(r"\mathbbm{1}", r"\mathbbm", id="misspelt-font-on-a-digit"),
        pytest.param(r"\mathcolor{red}{x}", r"\mathcolor", id="command-latex2mathml-reads-as-a-font"),
        pytest.param(r"\math{x}", r"\math", id="bare-font-prefix"),
        pytest.param(r"a \< b", r"\<", id="backslash-before-a-symbol"),
        pytest.param("x \\", "\\", id="trailing-backslash"),
        pytest.param(r"\hspace{\simga}", r"\simga", id="unknown-command-as-a-width"),
        pytest.param(r"\big\langl", r"\langl", id="unknown-command-as-a-delimiter"),
        pytest.param(r"a \[ b", r"\[", id="escaped-bracket-the-converter-leaves-as-written"),
    ],
)
def test_an_unknown_command_fails_naming_it(expression: str, command: str) -> None:
    with pytest.raises(ReportError) as raised:
        mathml(expression, "block")

    assert str(raised.value) == (
        f"math expression '{expression}' uses {command}, which latex2mathml does not know: check its "
        r"spelling, or write \text{...} for literal text"
    )


@pytest.mark.parametrize(
    ("expression", "markup"),
    [
        pytest.param(
            r"\newcommand{\R}{\mathbb{R}} \R", "<mi>\N{DOUBLE-STRUCK CAPITAL R}</mi>", id="newcommand"
        ),
        pytest.param(r"\newcommand\R{x} \R", "<mi>x</mi>", id="newcommand-without-braces"),
        pytest.param(r"\def\R{x} \R", "<mi>x</mi>", id="def"),
        pytest.param(r"\DeclareMathOperator{\Tr}{Tr} \Tr A", "<mo>Tr</mo><mi>A</mi>", id="math-operator"),
        pytest.param(
            r"\mathbb{RR}",
            '<mrow><mi mathvariant="double-struck">R</mi><mi mathvariant="double-struck">R</mi></mrow>',
            id="font-on-a-group",
        ),
        pytest.param(r"\textbf{\foo}", '<mtext mathvariant="bold">\\foo</mtext>', id="inside-bold-text"),
        pytest.param(r"\verb|\foo|", '<mtext mathvariant="monospace">\\foo</mtext>', id="inside-verb"),
    ],
)
def test_a_command_the_expression_defines_or_one_inside_literal_text_converts(
    expression: str, markup: str
) -> None:
    assert mathml(expression, "inline") == f"{MATH_OPEN}<mrow>{markup}</mrow></math>"


FRACTION_MISSING_A_PART = (
    r"a fraction missing a part: \frac, \dfrac, \cfrac and \binom each take two, as in \frac{a}{b}"
)
STACK_MISSING_A_PART = (
    r"a stacked expression missing a part: \overset, \underset and \stackrel each take two, "
    r"as in \overset{a}{b}"
)
SCRIPT_MISSING_A_PART = (
    "a subscript or superscript missing a part: a script attaches to what comes before it, as in x_i, "
    "or to an empty {} as in {}_a"
)


@pytest.mark.parametrize(
    ("expression", "missing"),
    [
        pytest.param(r"\frac{a}", FRACTION_MISSING_A_PART, id="frac"),
        pytest.param(r"\dfrac{a}", FRACTION_MISSING_A_PART, id="dfrac"),
        pytest.param(r"\cfrac{a}", FRACTION_MISSING_A_PART, id="cfrac"),
        pytest.param(r"\binom{a}", FRACTION_MISSING_A_PART, id="binom"),
        pytest.param(r"\overset{a}", STACK_MISSING_A_PART, id="overset"),
        pytest.param(r"\underset{a}", STACK_MISSING_A_PART, id="underset"),
        pytest.param(r"x + \stackrel{a}", STACK_MISSING_A_PART, id="stackrel"),
        pytest.param(r"\displaystyle_a", SCRIPT_MISSING_A_PART, id="subscript-on-a-style-switch"),
        pytest.param(r"\displaystyle^a", SCRIPT_MISSING_A_PART, id="superscript-on-a-style-switch"),
        pytest.param(r"\small_{a}^{b}", SCRIPT_MISSING_A_PART, id="both-scripts-on-a-size-switch"),
        pytest.param(r"x\limits", SCRIPT_MISSING_A_PART, id="limits-after-no-operator"),
    ],
)
def test_an_expression_missing_a_part_fails_naming_what_lacks_it(expression: str, missing: str) -> None:
    with pytest.raises(ReportError) as raised:
        mathml(expression, "block")

    assert str(raised.value) == f"math expression '{expression}' has {missing}"


def test_a_root_missing_a_part_fails(stub_converter: Callable[[Element], None]) -> None:
    root = Element("math")
    SubElement(SubElement(root, "mroot"), "mi").text = "x"
    stub_converter(root)

    with pytest.raises(ReportError) as raised:
        mathml("x", "inline")

    assert str(raised.value) == (
        r"math expression 'x' has a root missing a part: \sqrt[n]{x} takes an index and a radicand"
    )


@pytest.mark.parametrize(
    "tag", [pytest.param("msubsup", id="msubsup"), pytest.param("munderover", id="munderover")]
)
def test_a_two_script_form_with_only_two_parts_fails(
    stub_converter: Callable[[Element], None], tag: str
) -> None:
    root = Element("math")
    scripted = SubElement(root, tag)
    SubElement(scripted, "mi").text = "x"
    SubElement(scripted, "mi").text = "a"
    stub_converter(root)

    with pytest.raises(ReportError) as raised:
        mathml("x", "inline")

    assert str(raised.value) == f"math expression 'x' has {SCRIPT_MISSING_A_PART}"


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(r"\sum\limits_{i}^{n} a_i", id="limits-with-both-scripts"),
        pytest.param(r"\sum\limits_{i} a_i", id="limits-with-a-subscript"),
        pytest.param(r"\int\limits_0^1 f", id="integral-limits"),
        pytest.param(r"\sum\nolimits_a^b", id="nolimits"),
        pytest.param(r"\sideset{_a^b}{_c^d}\sum", id="sideset"),
        pytest.param(r"\sideset{}{}\sum", id="empty-sideset"),
        pytest.param(r"\xrightarrow[a]{b}", id="arrow-with-both-labels"),
        pytest.param(r"\xleftarrow[a]{}", id="arrow-with-an-empty-label"),
        pytest.param(r"{}^{a}x", id="script-on-an-empty-group"),
        pytest.param("{}_a", id="subscript-on-an-empty-group"),
        pytest.param("f'", id="prime"),
        pytest.param("f''", id="double-prime"),
        pytest.param("f'''_a", id="triple-prime-with-a-subscript"),
        pytest.param("f'^2", id="prime-with-a-superscript"),
        pytest.param(r"\sum_{\substack{i<n\\j<m}} a_{ij}", id="substack"),
        pytest.param(r"\overset{a}{b} \underset{c}{d} \stackrel{e}{f}", id="stacks"),
        pytest.param(r"\overset{}{} \underset{a}{}", id="stacks-with-empty-parts"),
        pytest.param(r"\overbrace{a}^{b} \underbrace{c}_{d}", id="braces-with-labels"),
        pytest.param(r"\sqrt[3]{x} \root 3 \of y \sqrt[3]{}", id="roots"),
        pytest.param(r"\lim_{x\to 0} \max_x \operatorname*{arg\,max}_x", id="operator-limits"),
        pytest.param(r"\mathop{x}\limits^a_b", id="mathop-limits"),
        pytest.param(r"x_a^b x^b_a x_{} a^{}", id="scripts-in-either-order-and-empty"),
        pytest.param(r"\frac{}{} a \over b a \atop b a \choose b", id="fractions"),
        pytest.param(r"x \pmod{n}_a", id="script-after-a-modulus"),
    ],
)
def test_a_scripted_or_stacked_form_with_every_part_converts(expression: str) -> None:
    assert mathml(expression, "block").startswith('<math xmlns="http://www.w3.org/1998/Math/MathML"')


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param("a $$ b", id="spaced"),
        pytest.param("x\n$$\ny", id="own-line"),
        pytest.param(r"\$$", id="escaped-dollar-then-a-dollar"),
    ],
)
def test_a_double_dollar_fails_because_it_ends_a_notion_equation(expression: str) -> None:
    with pytest.raises(ReportError) as raised:
        mathml(expression, "block")

    assert str(raised.value) == (
        f"math expression '{expression}' holds $$, which ends a Notion equation early: "
        r"write \$\$ for literal dollars"
    )


def test_escaped_dollars_side_by_side_convert() -> None:
    assert mathml(r"\$\$", "inline") == f"{MATH_OPEN}<mrow><mi>$</mi><mi>$</mi></mrow></math>"


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param("x^", id="missing-superscript"),
        pytest.param(r"\frac", id="fraction-without-arguments"),
        pytest.param("", id="empty"),
        pytest.param(r"\color", id="command-without-argument"),
        pytest.param(r"\left( x", id="left-without-right"),
    ],
)
def test_an_expression_the_converter_rejects_fails_naming_it(expression: str) -> None:
    with pytest.raises(ReportError) as raised:
        mathml(expression, "block")

    assert str(raised.value).startswith(f"invalid math expression '{expression}': {CONVERTER_PREFIX}")


def test_a_converter_failure_names_the_exception_latex2mathml_raised() -> None:
    with pytest.raises(ReportError) as raised:
        mathml("x^", "block")

    assert str(raised.value) == (
        "invalid math expression 'x^': latex2mathml cannot convert it (MissingSuperScriptOrSubscriptError)"
    )


def test_a_converter_failure_keeps_the_exception_latex2mathml_raised_as_its_cause() -> None:
    with pytest.raises(ReportError) as raised:
        mathml("x^", "block")

    assert type(raised.value.__cause__) is MissingSuperScriptOrSubscriptError
