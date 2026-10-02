import re

import pytest

from skaldr.errors import ReportError
from skaldr.models import ToneLiteral
from skaldr.richtext import (
    AnchorLink,
    Citation,
    Code,
    InlineMath,
    Link,
    Placeholder,
    Plain,
    Rich,
    RichContext,
    ScriptPosition,
    ScriptText,
    Styled,
    StyleName,
    Tinted,
    parse_rich,
    visible_text,
    write_runs,
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
            (Plain("[l](https://a.io/"), Citation("sop", 1, "https://example.com/sop"), Plain(")")),
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


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param("++u++", (Styled("underline", (Plain("u"),)),), id="underline"),
        pytest.param(
            "an ++under *line*++ here",
            (
                Plain("an "),
                Styled("underline", (Plain("under "), Styled("italic", (Plain("line"),)))),
                Plain(" here"),
            ),
            id="underline-holding-italic",
        ),
        pytest.param(
            "H~2~O", (Plain("H"), ScriptText("subscript", "2"), Plain("O")), id="subscript-inside-a-word"
        ),
        pytest.param("10^3^", (Plain("10"), ScriptText("superscript", "3")), id="superscript"),
        pytest.param(
            "x~i,j~ and e^-1^",
            (Plain("x"), ScriptText("subscript", "i,j"), Plain(" and e"), ScriptText("superscript", "-1")),
            id="punctuation-inside-a-script",
        ),
        pytest.param(
            "~~old~~ H~2~O",
            (Styled("strike", (Plain("old"),)), Plain(" H"), ScriptText("subscript", "2"), Plain("O")),
            id="strike-next-to-a-subscript",
        ),
        pytest.param(
            "~~a ~b~ c~~",
            (Styled("strike", (Plain("a "), ScriptText("subscript", "b"), Plain(" c"))),),
            id="subscript-inside-a-strike",
        ),
        pytest.param(
            "**x^2^**",
            (Styled("bold", (Plain("x"), ScriptText("superscript", "2"))),),
            id="superscript-inside-bold",
        ),
        pytest.param(
            "++H~2~O++",
            (Styled("underline", (Plain("H"), ScriptText("subscript", "2"), Plain("O"))),),
            id="subscript-inside-underline",
        ),
        pytest.param("e^-i^", (Plain("e"), ScriptText("superscript", "-i")), id="signed-superscript"),
        pytest.param(
            "x~n+1~ z^*^ f^\N{PRIME}\N{PRIME}^ y~(k)~ x^\N{MINUS SIGN}1^",
            (
                Plain("x"),
                ScriptText("subscript", "n+1"),
                Plain(" z"),
                ScriptText("superscript", "*"),
                Plain(" f"),
                ScriptText("superscript", "\N{PRIME}\N{PRIME}"),
                Plain(" y"),
                ScriptText("subscript", "(k)"),
                Plain(" x"),
                ScriptText("superscript", "\N{MINUS SIGN}1"),
            ),
            id="operators-primes-and-parentheses-inside-a-script",
        ),
        pytest.param(
            "++i over i++",
            (Styled("underline", (Plain("i over i"),)),),
            id="two-increments-in-one-paragraph-read-as-an-underline",
        ),
    ],
)
def test_underline_and_script_marks_parse_into_runs(text: str, runs: Rich) -> None:
    assert parse_rich(text, FULL_CONTEXT) == runs


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("about ~5 days", id="lone-tilde"),
        pytest.param("cut from ~5 days~ to 2", id="whitespace-inside-a-subscript"),
        pytest.param("2^10 and 2^ 10^", id="unclosed-and-spaced-superscript"),
        pytest.param("~~unclosed~", id="strike-opener-with-one-closing-tilde"),
        pytest.param("a^^b^^", id="doubled-carets"),
        pytest.param("[^a][^b]", id="unknown-citations-side-by-side"),
        pytest.param("C++ and C++", id="cplusplus-twice"),
        pytest.param("i++ then j++", id="increments"),
        pytest.param("a ++ b ++ c", id="spaced-pluses"),
        pytest.param("++unclosed", id="unclosed-underline"),
        pytest.param("x++y++", id="underline-inside-a-word"),
        pytest.param("~/code,~/notes", id="home-directory-paths"),
        pytest.param("http://host/~alice/x~bob", id="url-with-tildes"),
        pytest.param("C:\\~tmp~\\x", id="windows-path-with-tildes"),
        pytest.param("(^|[^\\p{L}])", id="regex-with-carets"),
        pytest.param("cut ~5%~ of it", id="percent-inside-tildes"),
        pytest.param("2^a_b^ and x~a/b~", id="underscore-and-slash-inside-markers"),
    ],
)
def test_marker_characters_that_do_not_form_a_mark_stay_prose(text: str) -> None:
    assert parse_rich(text, FULL_CONTEXT) == (Plain(text),)


def test_a_subscript_cannot_hold_a_code_span() -> None:
    assert parse_rich("x~`i`~") == (Plain("x~"), Code("i"), Plain("~"))


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param("a $`x_i`$ b", (Plain("a "), InlineMath("x_i"), Plain(" b")), id="inline-math"),
        pytest.param("$` \\frac{a}{b} `$", (InlineMath("\\frac{a}{b}"),), id="outer-spaces-are-trimmed"),
        pytest.param(
            "$`x` and `y`$",
            (Plain("$"), Code("x"), Plain(" and "), Code("y"), Plain("$")),
            id="two-code-spans-between-dollars",
        ),
        pytest.param("`$x$`", (Code("$x$"),), id="dollars-inside-a-code-span"),
        pytest.param("$`x`", (Plain("$"), Code("x")), id="no-closing-dollar"),
        pytest.param("costs $5 and $x$", (Plain("costs $5 and $x$"),), id="prose-dollars"),
        pytest.param(
            "[the $`x`$ term](https://e.com)",
            (Link((Plain("the "), InlineMath("x"), Plain(" term")), "https://e.com"),),
            id="inline-math-in-a-link-label",
        ),
        pytest.param(
            "**$`a^2`$**",
            (Styled("bold", (InlineMath("a^2"),)),),
            id="carets-inside-math-are-not-a-superscript",
        ),
    ],
)
def test_a_code_span_between_dollars_parses_into_inline_math(text: str, runs: Rich) -> None:
    assert parse_rich(text, FULL_CONTEXT) == runs


def test_inline_math_the_converter_rejects_fails_naming_the_expression() -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich("see $`x^`$ here")

    assert str(raised.value) == (
        "invalid math expression 'x^': latex2mathml cannot convert it (MissingSuperScriptOrSubscriptError)"
    )


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        pytest.param(
            r"\href{https://e.com}{x}",
            r"math expression '\href{https://e.com}{x}' sets the href attribute, which is not a MathML "
            r"attribute skaldr renders: leave out \href, \class and \style",
            id="href",
        ),
        pytest.param(
            r"\class{loud}{x}",
            r"math expression '\class{loud}{x}' sets the class attribute, which is not a MathML "
            r"attribute skaldr renders: leave out \href, \class and \style",
            id="class",
        ),
        pytest.param(
            r"\style{color:red}{x}",
            r"math expression '\style{color:red}{x}' sets the style attribute, which is not a MathML "
            r"attribute skaldr renders: leave out \href, \class and \style",
            id="style",
        ),
        pytest.param(
            "a$$b",
            r"math expression 'a$$b' holds $$, which ends a Notion equation early: "
            r"write \$\$ for literal dollars",
            id="double-dollar",
        ),
        pytest.param(
            r"\frac{a}",
            r"math expression '\frac{a}' has a fraction with one part: \frac, \dfrac, \cfrac and "
            r"\binom each take two, as in \frac{a}{b}",
            id="fraction-with-one-part",
        ),
    ],
)
def test_inline_math_that_cannot_render_fails_naming_the_expression(expression: str, message: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(f"see $`{expression}`$ here")

    assert str(raised.value) == message


def test_raw_markup_inside_inline_math_stays_part_of_the_expression() -> None:
    assert parse_rich(r"a $`\text{<script>x</script>}`$ b") == (
        Plain("a "),
        InlineMath(r"\text{<script>x</script>}"),
        Plain(" b"),
    )


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param("[late]{tone=danger}", (Tinted("danger", None, (Plain("late"),)),), id="color"),
        pytest.param("[due]{bg=warning}", (Tinted(None, "warning", (Plain("due"),)),), id="highlight"),
        pytest.param(
            "[now]{tone=danger bg=warning}",
            (Tinted("danger", "warning", (Plain("now"),)),),
            id="color-and-highlight",
        ),
        pytest.param(
            "[now]{ bg=warning   tone=danger }",
            (Tinted("danger", "warning", (Plain("now"),)),),
            id="either-order-with-extra-spaces",
        ),
        pytest.param(
            "[ok]{tone=green bg=amber}",
            (Tinted("success", "warning", (Plain("ok"),)),),
            id="palette-names-are-tone-aliases",
        ),
        pytest.param(
            "a [**very** `hot` H~2~O]{tone=danger} b",
            (
                Plain("a "),
                Tinted(
                    "danger",
                    None,
                    (
                        Styled("bold", (Plain("very"),)),
                        Plain(" "),
                        Code("hot"),
                        Plain(" H"),
                        ScriptText("subscript", "2"),
                        Plain("O"),
                    ),
                ),
                Plain(" b"),
            ),
            id="marks-inside-the-span",
        ),
        pytest.param(
            "[{{who}} 10^3^ [^sop]]{bg=info}",
            (
                Tinted(
                    None,
                    "info",
                    (
                        Placeholder("who"),
                        Plain(" 10"),
                        ScriptText("superscript", "3"),
                        Plain(" "),
                        Citation("sop", 1, "https://example.com/sop"),
                    ),
                ),
            ),
            id="placeholder-script-and-citation-inside-the-span",
        ),
        pytest.param(
            "[[a]{tone=danger}](https://x.io)",
            (Link((Tinted("danger", None, (Plain("a"),)),), "https://x.io"),),
            id="span-inside-a-link-label",
        ),
        pytest.param(
            "[[a]{tone=danger} b](#method)",
            (AnchorLink((Tinted("danger", None, (Plain("a"),)), Plain(" b")), "method"),),
            id="span-inside-an-anchor-link-label",
        ),
        pytest.param(
            "[x](https://x.io/~a~/b^c^) [y]{tone=info}",
            (Link((Plain("x"),), "https://x.io/~a~/b^c^"), Plain(" "), Tinted("info", None, (Plain("y"),))),
            id="script-markers-inside-a-url-stay-in-the-url",
        ),
        pytest.param(
            "**a [b]{tone=info} c**",
            (Styled("bold", (Plain("a "), Tinted("info", None, (Plain("b"),)), Plain(" c"))),),
            id="span-inside-bold",
        ),
        pytest.param(
            "[docs](https://e.com) [b]{tone=info}",
            (Link((Plain("docs"),), "https://e.com"), Plain(" "), Tinted("info", None, (Plain("b"),))),
            id="link-next-to-a-span",
        ),
        pytest.param(
            "[a]{tone=info}(https://e.com)",
            (Tinted("info", None, (Plain("a"),)), Plain("(https://e.com)")),
            id="parentheses-after-a-span-are-not-a-link",
        ),
    ],
)
def test_an_attribute_span_parses_into_a_tinted_run(text: str, runs: Rich) -> None:
    assert parse_rich(text, FULL_CONTEXT) == runs


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("[a]{x}", id="braces-without-an-attribute"),
        pytest.param("[a]{}", id="empty-braces"),
        pytest.param("[a] {tone=info}", id="space-before-the-braces"),
        pytest.param("{tone=info} alone", id="braces-without-a-label"),
        pytest.param("[a]{tone=info", id="unclosed-braces"),
        pytest.param("[a]{Tone=info}", id="capitalised-key"),
        pytest.param("arr[i]{n=3}", id="index-then-a-set-literal"),
        pytest.param("[a]{x=1}", id="unknown-key-alone"),
        pytest.param("[a]{size=2}", id="size-key-alone"),
        pytest.param("[a]{tones=info} [b]{bgcolor=red}", id="keys-that-only-start-with-tone-or-bg"),
        pytest.param("[a]{atone=info}", id="key-that-ends-with-tone"),
    ],
)
def test_brackets_and_braces_that_form_no_attribute_span_stay_prose(text: str) -> None:
    assert parse_rich(text, FULL_CONTEXT) == (Plain(text),)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param(
            "[a]{tone=purple}",
            "unknown tone 'purple' in {tone=purple}: a tone is one of neutral, info, success, warning, "
            "danger, accent, teal, sky, or a palette name slate, blue, green, amber, red, violet",
            id="unknown-tone",
        ),
        pytest.param(
            "[a]{bg=}",
            "unknown tone '' in {bg=}: a tone is one of neutral, info, success, warning, "
            "danger, accent, teal, sky, or a palette name slate, blue, green, amber, red, violet",
            id="empty-tone",
        ),
        pytest.param(
            "[a]{tone=bogus}",
            "unknown tone 'bogus' in {tone=bogus}: a tone is one of neutral, info, success, warning, "
            "danger, accent, teal, sky, or a palette name slate, blue, green, amber, red, violet",
            id="bogus-tone",
        ),
        pytest.param(
            "[a]{tone=info x=1}",
            "unknown attribute 'x' in {tone=info x=1}: a [text]{…} span takes tone=<tone> and bg=<tone>",
            id="unknown-attribute-after-a-tone",
        ),
        pytest.param(
            "[a]{size=2 bg=info}",
            "unknown attribute 'size' in {size=2 bg=info}: a [text]{…} span takes tone=<tone> and bg=<tone>",
            id="unknown-attribute-before-a-background",
        ),
        pytest.param(
            "[a]{tone=info tone=danger}",
            "attribute 'tone' is set twice in {tone=info tone=danger}",
            id="repeated-attribute",
        ),
        pytest.param(
            "[a]{tone = info}",
            "malformed attribute 'tone' in {tone = info}: write each attribute as key=value, "
            "with no spaces around '='",
            id="spaces-around-the-equals-sign",
        ),
    ],
)
def test_an_attribute_span_that_names_no_valid_tone_fails_naming_the_token(text: str, message: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(f"x {text} y")

    assert str(raised.value) == message


@pytest.mark.parametrize(
    ("text", "token"),
    [
        pytest.param("[see [docs](https://x.io) now]{tone=info}", "{tone=info}", id="link-inside-the-span"),
        pytest.param("[see [^nope] now]{bg=warning}", "{bg=warning}", id="unresolved-citation-inside"),
        pytest.param("[]{tone=info}", "{tone=info}", id="empty-text"),
        pytest.param("[a [b] c]{ tone=danger bg=info }", "{tone=danger bg=info}", id="bracket-inside"),
    ],
)
def test_an_attribute_list_that_colors_no_text_fails_naming_the_token(text: str, token: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(f"x {text} y", FULL_CONTEXT)

    assert str(raised.value) == (
        f"the attribute list {token} follows no [text] it can color: the text inside a [text]{{…}} span "
        "is not empty and holds no link and no other [ or ]"
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


def test_visible_text_reads_every_run_as_a_reader_would() -> None:
    runs: Rich = (
        Plain("a "),
        Link((Code("b"),), "https://e.com"),
        Citation("k", 2),
        Placeholder("who"),
        Styled("bold", (Plain("!"),)),
        Styled("underline", (Plain(" H"),)),
        ScriptText("subscript", "2"),
        Plain("O "),
        ScriptText("superscript", "3"),
        Tinted("danger", "warning", (Plain(" hot"),)),
        Plain(" "),
        InlineMath("x_i"),
    )

    assert visible_text(runs) == "a b[2]who! H2O 3 hot x_i"


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

    def script(self, position: ScriptPosition, text: str, /) -> str:
        return f"<{position}:{text}>"

    def tinted(self, tone: ToneLiteral | None, background: ToneLiteral | None, inner: str, /) -> str:
        return f"<tint:{tone}/{background}:{inner}>"

    def math(self, expression: str, /) -> str:
        return f"<math:{expression}>"


def test_write_runs_hands_every_run_to_its_writer_method_in_order() -> None:
    runs = parse_rich(
        "a `c` [see `x` [^sop]](https://e.com) [m](#method) {{who}} ~~*x*~~ ++u++ H~2~O 10^3^ "
        "[*hot*]{bg=danger} $`x_i`$",
        FULL_CONTEXT,
    )

    assert write_runs(runs, _TaggedRuns()) == (
        "a <code:c> <link:see <code:x> <cite:sop=1>|https://e.com> <anchor:m|method> <blank:who> "
        "<strike:<italic:x>> <underline:u> H<subscript:2>O 10<superscript:3> <tint:None/danger:<italic:hot>> "
        "<math:x_i>"
    )
