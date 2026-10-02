import pytest
from markdown_it.token import Token

from skaldr.errors import ReportError
from skaldr.richtext_syntax import inline_tokens

Shape = tuple[tuple[str, object], ...]
REFERENCE_KEYS = frozenset({"sop"})


def _payload(token: Token) -> object:
    if token.type == "link_open":
        return token.attrs["href"]
    return token.content


def _shape(text: str) -> Shape:
    return tuple(
        (token.type, _payload(token))
        for token in inline_tokens(text, REFERENCE_KEYS)
        if token.type != "text" or token.content
    )


@pytest.mark.parametrize(
    ("text", "shape"),
    [
        pytest.param(
            "**a *b* c**",
            (
                ("strong_open", ""),
                ("text", "a "),
                ("em_open", ""),
                ("text", "b"),
                ("em_close", ""),
                ("text", " c"),
                ("strong_close", ""),
            ),
            id="italic-inside-bold",
        ),
        pytest.param(
            "~~old~~ `x`",
            (("s_open", ""), ("text", "old"), ("s_close", ""), ("text", " "), ("code_inline", "x")),
            id="strike-and-code",
        ),
        pytest.param(
            "[a](https://en.wikipedia.org/wiki/Foo_(bar))",
            (("link_open", "https://en.wikipedia.org/wiki/Foo_(bar)"), ("text", "a"), ("link_close", "")),
            id="balanced-parentheses-in-a-url",
        ),
        pytest.param(
            "[a](https://x.io/~a~/b^c^)",
            (("link_open", "https://x.io/~a~/b^c^"), ("text", "a"), ("link_close", "")),
            id="a-url-is-kept-as-written",
        ),
        pytest.param(
            "[s](#method) [m](mailto:a@b.io)",
            (
                ("link_open", "#method"),
                ("text", "s"),
                ("link_close", ""),
                ("text", " "),
                ("link_open", "mailto:a@b.io"),
                ("text", "m"),
                ("link_close", ""),
            ),
            id="anchor-and-mailto-links",
        ),
        pytest.param("\\*not\\* \\`code\\`", (("text", "*not* `code`"),), id="backslash-escapes"),
    ],
)
def test_commonmark_inline_syntax_becomes_tokens(text: str, shape: Shape) -> None:
    assert _shape(text) == shape


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("2 * 3 * 4", id="spaced-asterisks"),
        pytest.param("x**(y)**z", id="closer-between-punctuation-and-a-letter"),
        pytest.param("[x](javascript:alert(1))", id="disallowed-scheme"),
        pytest.param("[x](HTTPS://e.com)", id="scheme-in-capitals"),
        pytest.param("[x][y] [z]", id="reference-links-without-definitions"),
        pytest.param("<https://e.com> <b>x</b>", id="autolink-and-raw-html"),
        pytest.param("&amp; &copy;", id="entity-references"),
        pytest.param("a  \nb", id="trailing-spaces-before-a-newline"),
    ],
)
def test_markup_skaldr_does_not_read_stays_text(text: str) -> None:
    assert _shape(text) == (("text", text),)


@pytest.mark.parametrize(
    ("text", "shape"),
    [
        pytest.param(
            "{{ owner }} [^sop]",
            (("placeholder", "owner"), ("text", " "), ("citation", "sop")),
            id="blank-and-citation",
        ),
        pytest.param(
            "[see {{who}} [^sop]](https://e.com/a)",
            (
                ("link_open", "https://e.com/a"),
                ("text", "see "),
                ("placeholder", "who"),
                ("text", " "),
                ("citation", "sop"),
                ("link_close", ""),
            ),
            id="blank-and-citation-in-a-link-label",
        ),
        pytest.param(
            "[pr](https://x.io/{{pr}})",
            (("text", "[pr](https://x.io/"), ("placeholder", "pr"), ("text", ")")),
            id="a-url-holding-a-blank-is-no-link",
        ),
        pytest.param(
            "$`x_i`$ and $`x` and `y`$",
            (
                ("inline_math", "x_i"),
                ("text", " and $"),
                ("code_inline", "x"),
                ("text", " and "),
                ("code_inline", "y"),
                ("text", "$"),
            ),
            id="math-and-two-code-spans-between-dollars",
        ),
        pytest.param(
            "`{{x}}` `$`a`$`",
            (
                ("code_inline", "{{x}}"),
                ("text", " "),
                ("code_inline", "$"),
                ("text", "a"),
                ("code_inline", "$"),
            ),
            id="markers-inside-code",
        ),
    ],
)
def test_blanks_citations_and_inline_math_become_tokens(text: str, shape: Shape) -> None:
    assert _shape(text) == shape


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("a {{b{c}} d", id="brace-inside-a-blank"),
        pytest.param("{{unclosed", id="unclosed-blank"),
        pytest.param("see [^nope] and [^a.b]", id="unknown-and-malformed-citations"),
        pytest.param("costs $5 and $x$ and $``$", id="prose-dollars"),
    ],
)
def test_text_that_forms_no_blank_citation_or_math_stays_text(text: str) -> None:
    assert _shape(text) == (("text", text),)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param(
            "a {{two words}} b",
            "invalid placeholder '{{two words}}': a placeholder name is letters, digits, '_' or '-' only "
            "(a fill-me-later blank is written {{name}}; for a literal {{ use a `code` span)",
            id="malformed-blank",
        ),
        pytest.param(
            "see $` `$",
            "inline math $` `$ is empty: write an expression between $` and `$, as in $`x_i`$",
            id="empty-math",
        ),
        pytest.param(
            "see $`x^`$",
            "invalid math expression 'x^': latex2mathml cannot convert it "
            "(MissingSuperScriptOrSubscriptError)",
            id="math-the-converter-refuses",
        ),
    ],
)
def test_a_malformed_blank_or_math_span_fails_naming_it(text: str, message: str) -> None:
    with pytest.raises(ReportError) as raised:
        inline_tokens(text)

    assert str(raised.value) == message
