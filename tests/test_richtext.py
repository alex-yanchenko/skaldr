import re

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
    StyleName,
    parse_rich,
    write_runs,
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
        pytest.param(
            "[l](https://a.io/[^sop])",
            (Plain("[l](https://a.io/"), Citation("sop", 1), Plain(")")),
            id="citation-inside-a-url-is-not-a-link",
        ),
        pytest.param(
            "~~a *b~~ c*",
            (Styled("strike", (Plain("a *b"),)), Plain(" c*")),
            id="emphasis-crossing-a-strike-stays-inside-the-strike",
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


@pytest.mark.parametrize("text", ["[x](#method`y`)", "[x](#method[^sop])"])
def test_an_anchor_link_whose_target_holds_a_code_span_or_citation_fails(text: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(text, FULL_CONTEXT)

    assert str(raised.value) == (
        "rich text links to the anchor '#method…', whose target holds a `code` span or [^citation]; "
        "an anchor link targets a heading or section id"
    )


@pytest.mark.parametrize("token", ["{{a.b}}", "{{two words}}", "{{}}"])
def test_a_malformed_placeholder_fails_naming_it(token: str) -> None:
    with pytest.raises(ReportError, match=rf"invalid placeholder '{re.escape(token)}'"):
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


class _TaggedRuns:
    def text(self, text: str, /) -> str:
        return text

    def code(self, text: str, /) -> str:
        return f"<code:{text}>"

    def link(self, label: str, url: str, /) -> str:
        return f"<link:{label}|{url}>"

    def anchor_link(self, label: str, anchor: str, /) -> str:
        return f"<anchor:{label}|{anchor}>"

    def citation(self, run: Citation, /) -> str:
        return f"<cite:{run.key}={run.number}>"

    def placeholder(self, name: str, /) -> str:
        return f"<blank:{name}>"

    def styled(self, style: StyleName, inner: str, /) -> str:
        return f"<{style}:{inner}>"


def test_write_runs_hands_every_run_to_its_writer_method_in_order() -> None:
    runs = parse_rich("a `c` [see `x` [^sop]](https://e.com) [m](#method) {{who}} ~~*x*~~", FULL_CONTEXT)

    assert write_runs(runs, _TaggedRuns()) == (
        "a <code:c> <link:see <code:x> <cite:sop=1>|https://e.com> <anchor:m|method> <blank:who> "
        "<strike:<italic:x>>"
    )
