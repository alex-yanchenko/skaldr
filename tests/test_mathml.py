import pytest

from skaldr.errors import ReportError
from skaldr.mathml import MathDisplay, mathml

MATH_OPEN = '<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">'


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
        pytest.param(
            r"\alpha + \beta",
            "<mrow><mi>\N{GREEK SMALL LETTER ALPHA}</mi><mo>+</mo>"
            "<mi>\N{GREEK SMALL LETTER BETA}</mi></mrow>",
            id="greek-letters",
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
        f"math expression '{expression}' sets the {attribute} attribute, which skaldr does not render: "
        r"leave out \href, \class and \style"
    )


@pytest.mark.parametrize(
    ("expression", "reason"),
    [
        pytest.param("x^", "MissingSuperScriptOrSubscriptError", id="missing-superscript"),
        pytest.param(r"\frac", "NoAvailableTokensError", id="fraction-without-arguments"),
        pytest.param("", "NoAvailableTokensError", id="empty"),
        pytest.param(r"\color", "StopIteration", id="command-without-argument"),
    ],
)
def test_an_expression_the_converter_rejects_fails_naming_it(expression: str, reason: str) -> None:
    with pytest.raises(ReportError) as raised:
        mathml(expression, "block")

    assert str(raised.value) == (
        f"invalid math expression '{expression}': latex2mathml cannot convert it ({reason})"
    )
