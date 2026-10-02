import pytest
from markdown_it.token import Token

from skaldr.errors import ReportError
from skaldr.richtext_syntax import SPAN_TONES, SpanTones, inline_tokens

Shape = tuple[tuple[str, object], ...]
REFERENCE_KEYS = frozenset({"sop"})


def _payload(token: Token) -> object:
    if token.type == "link_open":
        return token.attrs["href"]
    return token.meta.get(SPAN_TONES, token.content)


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


@pytest.mark.parametrize(
    ("text", "shape"),
    [
        pytest.param(
            "[now]{ bg=warning   tone=red }",
            (("tint_open", SpanTones("danger", "warning")), ("text", "now"), ("tint_close", "")),
            id="both-attributes-in-either-order",
        ),
        pytest.param(
            "[a [b] c]{tone=info}",
            (("tint_open", SpanTones("info", None)), ("text", "a [b] c"), ("tint_close", "")),
            id="balanced-brackets-in-the-text",
        ),
        pytest.param(
            "[{{who}} [^sop]]{bg=info}",
            (
                ("tint_open", SpanTones(None, "info")),
                ("placeholder", "who"),
                ("text", " "),
                ("citation", "sop"),
                ("tint_close", ""),
            ),
            id="blank-and-citation-in-the-text",
        ),
        pytest.param(
            "[[a]{tone=danger}](https://x.io)",
            (
                ("link_open", "https://x.io"),
                ("tint_open", SpanTones("danger", None)),
                ("text", "a"),
                ("tint_close", ""),
                ("link_close", ""),
            ),
            id="span-inside-a-link-label",
        ),
        pytest.param(
            "[a]{tone=info}(https://e.com)",
            (
                ("tint_open", SpanTones("info", None)),
                ("text", "a"),
                ("tint_close", ""),
                ("text", "(https://e.com)"),
            ),
            id="parentheses-after-a-span-are-not-a-link",
        ),
        pytest.param(
            "[x](https://a.b/?q=[a]{tone=info})",
            (("link_open", "https://a.b/?q=[a]{tone=info}"), ("text", "x"), ("link_close", "")),
            id="span-syntax-inside-a-url",
        ),
    ],
)
def test_a_bracketed_span_with_tone_attributes_becomes_tint_tokens(text: str, shape: Shape) -> None:
    assert _shape(text) == shape


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("[a]{x} [a]{} [a]{x=1} [a]{size=2}", id="braces-without-a-tone-or-bg-key"),
        pytest.param("arr[i]{n=3}", id="index-then-a-set-literal"),
        pytest.param("[a] {tone=info}", id="space-before-the-braces"),
        pytest.param("[a]{Tone=info} [a]{tones=info} [a]{atone=info}", id="keys-that-are-not-tone-or-bg"),
        pytest.param("[a]{tone=info", id="unclosed-braces"),
        pytest.param("{tone=info} alone", id="braces-without-a-label"),
    ],
)
def test_brackets_and_braces_that_form_no_span_stay_text(text: str) -> None:
    assert _shape(text) == (("text", text),)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param(
            "x []{tone=info} y",
            "the attribute list {tone=info} follows no [text] it can color: the text inside a [text]{…} span "
            "is not empty and holds no link",
            id="empty-text",
        ),
        pytest.param(
            "[see [docs](https://x.io) now]{ tone=info }",
            "the attribute list {tone=info} follows no [text] it can color: the text inside a [text]{…} span "
            "is not empty and holds no link",
            id="link-inside-the-text",
        ),
        pytest.param(
            "x ]{bg=info} y",
            "the attribute list {bg=info} follows no [text] it can color: the text inside a [text]{…} span "
            "is not empty and holds no link",
            id="unopened-bracket",
        ),
        pytest.param(
            "[a]{tone= info}",
            "malformed attribute 'tone=' in {tone= info}: write each attribute as key=value, "
            "with no spaces around '='",
            id="space-after-the-equals-sign",
        ),
        pytest.param(
            "[a]{tone=info `c`}",
            "malformed attribute '`c`' in {tone=info `c`}: write each attribute as key=value, "
            "with no spaces around '='",
            id="markup-inside-the-braces",
        ),
        pytest.param(
            "[a]{tone=info tone=danger}",
            "attribute 'tone' is set twice in {tone=info tone=danger}",
            id="repeated-attribute",
        ),
    ],
)
def test_an_attribute_list_that_cannot_color_text_fails_naming_it(text: str, message: str) -> None:
    with pytest.raises(ReportError) as raised:
        inline_tokens(text)

    assert str(raised.value) == message
