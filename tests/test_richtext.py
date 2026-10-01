import pytest

from skaldr.errors import ReportError
from skaldr.richtext import (
    AnchorLink,
    Chip,
    Citation,
    Code,
    Link,
    Placeholder,
    Plain,
    Rich,
    RichContext,
    Styled,
    parse_rich,
    visible_text,
)

FULL_CONTEXT = RichContext(
    reference_numbers={"sop": 1},
    reference_urls={"sop": "https://example.com/sop"},
    anchor_ids=frozenset({"method"}),
)


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
        Citation("sop", 1, "https://example.com/sop"),
        Plain(" "),
        Placeholder("owner"),
    )


def test_a_link_label_keeps_a_citation_and_a_code_span() -> None:
    assert parse_rich("[see `x` [^sop]](https://example.com/a)", FULL_CONTEXT) == (
        Link(
            (Plain("see "), Code("x"), Plain(" "), Citation("sop", 1, "https://example.com/sop")),
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


def test_visible_text_reads_every_run_as_a_reader_would() -> None:
    runs: Rich = (
        Plain("a "),
        Link((Code("b"),), "https://e.com"),
        Citation("k", 2),
        Placeholder("who"),
        Chip("api", "blue"),
        Styled("bold", (Plain("!"),)),
    )

    assert visible_text(runs) == "a b[2]whoapi!"
