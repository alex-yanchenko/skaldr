from collections.abc import Callable, Iterator
from xml.etree.ElementTree import Element, SubElement

import pytest

from skaldr import mathml as mathml_module
from skaldr.errors import ReportError
from skaldr.mathml import MATHML_ATTRIBUTES, MathDisplay, mathml

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
    ],
)
def test_a_unicode_code_point_decodes_and_one_no_page_can_hold_becomes_the_replacement_character(
    expression: str, character: str
) -> None:
    assert mathml(expression, "inline") == f"{MATH_OPEN}<mrow><mi>{character}</mi></mrow></math>"


def test_an_attribute_value_cannot_close_its_quotes() -> None:
    assert mathml(r'\color{red" onload="x}{y}', "inline") == (
        f'{MATH_OPEN}<mrow><mstyle mathcolor="red&quot; onload=&quot;x"><mrow><mi>y</mi></mrow></mstyle>'
        "</mrow></math>"
    )


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
    SubElement(root, "mi", {name: "v"}).text = "x"
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

    assert mathml("x", "inline") == f'<math><mi {attribute}="v">x</mi></math>'


def test_the_allowlist_is_the_set_of_attributes_latex2mathml_emits() -> None:
    assert sorted(MATHML_ATTRIBUTES) == [
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
    ]


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
    ],
)
def test_an_unknown_command_fails_naming_it(expression: str, command: str) -> None:
    with pytest.raises(ReportError) as raised:
        mathml(expression, "block")

    assert str(raised.value) == (
        f"math expression '{expression}' uses {command}, which latex2mathml does not know: check its "
        r"spelling, or write \text{...} for literal text"
    )


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
