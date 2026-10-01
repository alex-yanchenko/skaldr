import pytest

from skaldr.errors import ReportError
from skaldr.richtext import (
    AnchorLink,
    Citation,
    Code,
    Link,
    Placeholder,
    Plain,
    Rich,
    RichContext,
    Styled,
    parse_rich,
)

FULL_CONTEXT = RichContext(reference_numbers={"sop": 1}, anchor_ids=frozenset({"method"}))


def test_rich_text_parses_into_runs() -> None:
    runs = parse_rich(
        "a **bold `x`** and ~~old **new**~~ see [the method](#method), "
        "[docs](https://example.com/d) [^sop] {{owner}}",
        FULL_CONTEXT,
    )

    assert runs == (
        Plain("a "),
        Styled("bold", (Plain("bold "), Code("x"))),
        Plain(" and "),
        Styled("strike", (Plain("old "), Styled("bold", (Plain("new"),)))),
        Plain(" see "),
        AnchorLink((Plain("the method"),), "method"),
        Plain(", "),
        Link((Plain("docs"),), "https://example.com/d"),
        Plain(" "),
        Citation("sop", 1),
        Plain(" "),
        Placeholder("owner"),
    )


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param("*a*", (Styled("italic", (Plain("a"),)),), id="italic"),
        pytest.param(
            "*a **b** c*",
            (Styled("italic", (Plain("a "), Styled("bold", (Plain("b"),)), Plain(" c"))),),
            id="bold-inside-italic",
        ),
        pytest.param(
            "**a *b* c**",
            (Plain("**a "), Styled("italic", (Plain("b"),)), Plain(" c**")),
            id="bold-cannot-wrap-an-asterisk-so-only-the-italic-applies",
        ),
        pytest.param("**a** b", (Styled("bold", (Plain("a"),)), Plain(" b")), id="bold-is-not-two-italics"),
        pytest.param("{{ owner }}", (Placeholder("owner"),), id="spaced-placeholder"),
        pytest.param(
            "[**x**](https://e.com)",
            (Link((Plain("**x**"),), "https://e.com"),),
            id="emphasis-in-a-link-label-stays-literal",
        ),
        pytest.param(
            "[l](https://a.io/`c`)",
            (Plain("[l](https://a.io/"), Code("c"), Plain(")")),
            id="code-span-inside-a-url-is-not-a-link",
        ),
    ],
)
def test_inline_forms_parse_into_runs(text: str, runs: Rich) -> None:
    assert parse_rich(text, FULL_CONTEXT) == runs


def test_a_link_label_keeps_a_citation_and_a_code_span() -> None:
    assert parse_rich("[see `x` [^sop]](https://example.com/a)", FULL_CONTEXT) == (
        Link(
            (Plain("see "), Code("x"), Plain(" "), Citation("sop", 1)),
            "https://example.com/a",
        ),
    )


@pytest.mark.parametrize(
    ("text", "context"),
    [
        pytest.param("[x](javascript:alert(1))", FULL_CONTEXT, id="disallowed-scheme"),
        pytest.param("see [^nope]", FULL_CONTEXT, id="unknown-footnote"),
        pytest.param("see [^sop]", RichContext(), id="no-reference-numbers"),
        pytest.param("[x](#method)", RichContext(), id="anchor-without-an-anchor-set"),
        pytest.param("a {{b{c}} d", FULL_CONTEXT, id="brace-inside-a-blank"),
    ],
)
def test_markup_the_context_cannot_resolve_stays_literal_text(text: str, context: RichContext) -> None:
    assert parse_rich(text, context) == (Plain(text),)


def test_a_link_to_an_unknown_anchor_fails() -> None:
    with pytest.raises(ReportError, match=r"unknown anchor '#nowhere'"):
        parse_rich("[x](#nowhere)", FULL_CONTEXT)


@pytest.mark.parametrize("token", ["{{a.b}}", "{{two words}}", "{{}}"])
def test_a_malformed_placeholder_fails_naming_it(token: str) -> None:
    with pytest.raises(ReportError, match=r"invalid placeholder '\{\{"):
        parse_rich(f"a {token} b")


def test_a_placeholder_wrapped_around_other_markup_fails_without_leaking_the_sentinel() -> None:
    with pytest.raises(ReportError, match=r"can't contain a link, `code` span") as raised:
        parse_rich("wrap {{ `code` }} it")

    assert "\x00" not in str(raised.value)


def test_nul_bytes_in_the_input_are_dropped() -> None:
    assert parse_rich("a\x00b **c**") == (Plain("ab "), Styled("bold", (Plain("c"),)))


def test_an_asterisk_inside_a_url_or_code_span_is_not_emphasis() -> None:
    assert parse_rich("[x](https://e.com/a*b*c) `*y*`") == (
        Link((Plain("x"),), "https://e.com/a*b*c"),
        Plain(" "),
        Code("*y*"),
    )
