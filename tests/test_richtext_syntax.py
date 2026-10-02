import pytest
from markdown_it.token import Token

from skaldr.richtext_syntax import inline_tokens

Shape = tuple[tuple[str, object], ...]


def _payload(token: Token) -> object:
    if token.type == "link_open":
        return token.attrs["href"]
    return token.content


def _shape(text: str) -> Shape:
    return tuple(
        (token.type, _payload(token))
        for token in inline_tokens(text)
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
