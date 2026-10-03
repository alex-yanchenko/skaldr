import re
import time
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from skaldr import render
from skaldr.compute import paragraphs
from skaldr.errors import ReportError
from skaldr.export import inline
from skaldr.export.lower import lower_report
from skaldr.models import ToneLiteral, load_report
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
    rich_text_fields,
    visible_text,
    write_runs,
)
from tests.conftest import REPO_ROOT

FULL_CONTEXT = RichContext(
    reference_numbers={"sop": 1},
    reference_urls={"sop": "https://example.com/sop"},
    anchor_ids=frozenset({"method"}),
)


def _recording_parse_rich(seen: set[str]) -> Callable[[str, RichContext | None], Rich]:
    def parse(text: str, context: RichContext | None = None) -> Rich:
        seen.add(text)
        return parse_rich(text, context)

    return parse


@pytest.mark.parametrize("example", ["data/example.yaml", "examples/sales-pipeline.yaml"])
def test_every_text_the_page_and_the_export_parse_is_a_field_the_validation_pass_checks(
    monkeypatch: pytest.MonkeyPatch, example: str
) -> None:
    report = load_report(REPO_ROOT / example)
    parsed: set[str] = set()
    monkeypatch.setattr(render, "parse_rich", _recording_parse_rich(parsed))
    monkeypatch.setattr(inline, "parse_rich", _recording_parse_rich(parsed))

    render.render_html(report)
    lower_report(report)

    validated = {paragraph for _, text in rich_text_fields(report) for paragraph in paragraphs(text)}
    assert sorted(text for text in parsed - validated if text) == []


def _italics_nested(depth: int) -> Rich:
    runs: Rich = (Styled("italic", (Plain("a b"),)),)
    for _ in range(depth - 1):
        runs = (Styled("italic", (Plain("a "), *runs)),)
    return runs


def test_marks_nest_up_to_the_nesting_limit() -> None:
    assert parse_rich("*a " * 20 + "b" + "*" * 20) == _italics_nested(20)


def test_colored_spans_nest_up_to_the_nesting_limit() -> None:
    runs: Rich = (Plain("x"),)
    for _ in range(20):
        runs = (Tinted("info", None, runs),)

    assert parse_rich("[" * 20 + "x" + "]{tone=info}" * 20) == runs


def test_brackets_nested_past_the_limit_that_form_no_mark_stay_text() -> None:
    text = "[" * 30 + "x" + "]" * 30

    assert parse_rich(text) == (Plain(text),)


@pytest.mark.parametrize("depth", [21, 260])
@pytest.mark.parametrize(
    ("opener", "closer"),
    [
        pytest.param("*a ", "*", id="italic"),
        pytest.param("**a ", "**", id="bold"),
        pytest.param("[*a ", "*](https://a.io)", id="italic-inside-a-link"),
        pytest.param("[", "]{tone=info}", id="colored-span"),
    ],
)
def test_marks_nested_past_the_limit_fail_naming_it(opener: str, closer: str, depth: int) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(opener * depth + "b" + closer * depth)

    assert str(raised.value) == (
        "rich text nests more than 20 marks, links or [text]{…} spans inside one another: flatten it"
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
            (Styled("bold", (Plain("a "), Styled("italic", (Plain("b"),)), Plain(" c"))),),
            id="italic-inside-bold",
        ),
        pytest.param("**a** b", (Styled("bold", (Plain("a"),)), Plain(" b")), id="bold-is-not-two-italics"),
        pytest.param("{{ owner }}", (Placeholder("owner"),), id="spaced-placeholder"),
        pytest.param(
            "[**x**](https://e.com)",
            (Link((Styled("bold", (Plain("x"),)),), "https://e.com"),),
            id="emphasis-in-a-link-label",
        ),
        pytest.param(
            "[l](https://a.io/`c`)",
            (Link((Plain("l"),), "https://a.io/`c`"),),
            id="backticks-in-a-url-stay-part-of-the-url",
        ),
        pytest.param(
            "[l](https://a.io/[^sop])",
            (Link((Plain("l"),), "https://a.io/[^sop]"),),
            id="citation-syntax-in-a-url-stays-part-of-the-url",
        ),
        pytest.param(
            "*a **b* c**",
            (
                Styled(
                    "italic", (Plain("a "), Styled("italic", (Styled("italic", (Plain("b"),)), Plain(" c"))))
                ),
            ),
            id="italic-crossing-bold-pairs-by-the-commonmark-delimiter-rules",
        ),
        pytest.param(
            "_word_ snake_case a__init__b __init__",
            (
                Styled("italic", (Plain("word"),)),
                Plain(" snake_case a__init__b "),
                Styled("bold", (Plain("init"),)),
            ),
            id="underscores-emphasise-only-at-word-boundaries",
        ),
        pytest.param(
            "C:\\~tmp~\\x a\\*b\\*",
            (Plain("C:~tmp~\\x a*b*"),),
            id="a-backslash-before-punctuation-escapes-it",
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
        pytest.param("~2~O", (ScriptText("subscript", "2"), Plain("O")), id="subscript-at-the-start"),
        pytest.param("x~1.5~", (Plain("x"), ScriptText("subscript", "1.5")), id="decimal-subscript"),
        pytest.param("x^a=b^", (Plain("x"), ScriptText("superscript", "a=b")), id="equals-in-a-superscript"),
        pytest.param("x~A~", (Plain("x"), ScriptText("subscript", "A")), id="capital-subscript"),
        pytest.param("e^π^", (Plain("e"), ScriptText("superscript", "π")), id="greek-letter-superscript"),
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
        pytest.param("++x++y", id="underline-closing-inside-a-word"),
        pytest.param("a ++b++c", id="underline-closing-into-a-word"),
        pytest.param("~/code,~/notes", id="home-directory-paths"),
        pytest.param("http://host/~alice/x~bob", id="url-with-tildes"),
        pytest.param("(^|[^\\p{L}])", id="regex-with-carets"),
        pytest.param("cut ~5%~ of it", id="percent-inside-tildes"),
        pytest.param("2^a_b^ and x~a/b~", id="underscore-and-slash-inside-markers"),
        pytest.param("x~a~~b", id="subscript-closer-followed-by-a-tilde"),
        pytest.param("^^b^", id="superscript-opener-after-a-caret"),
    ],
)
def test_marker_characters_that_do_not_form_a_mark_stay_prose(text: str) -> None:
    assert parse_rich(text, FULL_CONTEXT) == (Plain(text),)


def test_a_tilde_after_an_escaped_tilde_opens_no_subscript() -> None:
    assert parse_rich("\\~~x~") == (Plain("~~x~"),)


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param(
            "**bold with *italic* inside**",
            (Styled("bold", (Plain("bold with "), Styled("italic", (Plain("italic"),)), Plain(" inside"))),),
            id="bold-holding-italic",
        ),
        pytest.param(
            "[**bold** H~2~O ++u++](https://x.com)",
            (
                Link(
                    (
                        Styled("bold", (Plain("bold"),)),
                        Plain(" H"),
                        ScriptText("subscript", "2"),
                        Plain("O "),
                        Styled("underline", (Plain("u"),)),
                    ),
                    "https://x.com",
                ),
            ),
            id="marks-inside-a-link-label",
        ),
        pytest.param(
            "[a](https://en.wikipedia.org/wiki/Foo_(bar))",
            (Link((Plain("a"),), "https://en.wikipedia.org/wiki/Foo_(bar)"),),
            id="balanced-parentheses-in-a-link-url",
        ),
        pytest.param(
            "the **`api`**s",
            (Plain("the **"), Code("api"), Plain("**s")),
            id="bold-whose-closer-is-not-right-flanking-stays-literal",
        ),
    ],
)
def test_marks_follow_commonmark_emphasis_and_link_rules(text: str, runs: Rich) -> None:
    assert parse_rich(text, FULL_CONTEXT) == runs


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("2 * 3 * 4", id="spaced-asterisks"),
        pytest.param("a ** b ** c", id="spaced-double-asterisks"),
        pytest.param("x**(y)**z", id="bold-closer-between-punctuation-and-a-letter"),
        pytest.param("a ~~(b)~~c", id="strike-closer-between-punctuation-and-a-letter"),
    ],
)
def test_markers_that_commonmark_does_not_pair_stay_prose(text: str) -> None:
    assert parse_rich(text, FULL_CONTEXT) == (Plain(text),)


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param(
            "Review [the PR](https://github.com/acme/repo/pull/{{pr}}) now",
            (
                Plain("Review [the PR](https://github.com/acme/repo/pull/"),
                Placeholder("pr"),
                Plain(") now"),
            ),
            id="placeholder-in-a-link-url",
        ),
        pytest.param(
            "[ticket {{ticket}}](https://example.com/t)",
            (Link((Plain("ticket "), Placeholder("ticket")), "https://example.com/t"),),
            id="placeholder-in-a-link-label",
        ),
    ],
)
def test_a_placeholder_inside_a_link_stays_a_placeholder(text: str, runs: Rich) -> None:
    assert parse_rich(text, FULL_CONTEXT) == runs


@pytest.mark.parametrize("whitespace", [pytest.param(" ", id="spaces"), pytest.param("\n", id="newlines")])
def test_an_unclosed_placeholder_before_a_long_whitespace_run_parses_in_linear_time(whitespace: str) -> None:
    text = "{{" + whitespace * 5_000

    started = time.perf_counter()
    runs = parse_rich(text)
    elapsed = time.perf_counter() - started

    assert runs == (Plain(text),)
    assert elapsed < 2


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
            r"math expression '\frac{a}' has a fraction missing a part: \frac, \dfrac, \cfrac and "
            r"\binom each take two, as in \frac{a}{b}",
            id="fraction-missing-a-part",
        ),
    ],
)
def test_inline_math_that_cannot_render_fails_naming_the_expression(expression: str, message: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(f"see $`{expression}`$ here")

    assert str(raised.value) == message


@pytest.mark.parametrize("source", ["$` `$", "$`\t\n`$"])
def test_inline_math_holding_only_whitespace_fails_as_empty(source: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(f"see {source} here")

    assert str(raised.value) == (
        f"inline math {source} is empty: write an expression between $` and `$, as in $`x_i`$"
    )


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
            "malformed attribute 'bg=' in {bg=}: write each attribute as key=value, "
            "with no spaces around '='",
            id="empty-value",
        ),
        pytest.param(
            "[a]{tone=bogus}",
            "unknown tone 'bogus' in {tone=bogus}: a tone is one of neutral, info, success, warning, "
            "danger, accent, teal, sky, or a palette name slate, blue, green, amber, red, violet",
            id="bogus-tone",
        ),
        pytest.param(
            "[a]{tone=a=b}",
            "unknown tone 'a=b' in {tone=a=b}: a tone is one of neutral, info, success, warning, "
            "danger, accent, teal, sky, or a palette name slate, blue, green, amber, red, violet",
            id="second-equals-sign-stays-in-the-value",
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
        pytest.param(
            "[a]{tone= info}",
            "malformed attribute 'tone=' in {tone= info}: write each attribute as key=value, "
            "with no spaces around '='",
            id="space-after-the-equals-sign",
        ),
        pytest.param(
            "[a]{bg=\tinfo}",
            "malformed attribute 'bg=' in {bg=\tinfo}: write each attribute as key=value, "
            "with no spaces around '='",
            id="tab-after-the-equals-sign",
        ),
    ],
)
def test_an_attribute_span_that_names_no_valid_tone_fails_naming_the_token(text: str, message: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(f"x {text} y")

    assert str(raised.value) == message


def test_an_unknown_tone_keeps_the_validation_failure_as_its_cause() -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich("[a]{tone=purple}")

    assert type(raised.value.__cause__) is ValidationError


@pytest.mark.parametrize(
    ("text", "token"),
    [
        pytest.param("[see [docs](https://x.io) now]{tone=info}", "{tone=info}", id="link-inside-the-span"),
        pytest.param("[]{tone=info}", "{tone=info}", id="empty-text"),
        pytest.param("a]{ tone=danger bg=info }", "{tone=danger bg=info}", id="no-opening-bracket"),
    ],
)
def test_an_attribute_list_that_colors_no_text_fails_naming_the_token(text: str, token: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(f"x {text} y", FULL_CONTEXT)

    assert str(raised.value) == (
        f"the attribute list {token} follows no [text] it can color: the text inside a [text]{{…}} span "
        "is not empty and holds no link"
    )


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param(
            "[see [^nope] now]{bg=warning}",
            (Tinted(None, "warning", (Plain("see [^nope] now"),)),),
            id="unresolved-citation-inside",
        ),
        pytest.param(
            "[a [b] c]{ tone=danger bg=info }",
            (Tinted("danger", "info", (Plain("a [b] c"),)),),
            id="balanced-brackets-inside",
        ),
    ],
)
def test_the_text_of_a_span_may_hold_balanced_brackets(text: str, runs: Rich) -> None:
    assert parse_rich(text, FULL_CONTEXT) == runs


@pytest.mark.parametrize(
    ("text", "attribute", "token"),
    [
        pytest.param("[a]{tone=info `c`}", "`c`", "{tone=info `c`}", id="code-span"),
        pytest.param("[a]{tone=info [^sop]}", "[^sop]", "{tone=info [^sop]}", id="citation"),
        pytest.param(
            "[a]{bg=info $`x`$ tone=danger}", "$`x`$", "{bg=info $`x`$ tone=danger}", id="inline-math"
        ),
        pytest.param("[a]{tone=info [b](u)}", "[b](u)", "{tone=info [b](u)}", id="bare-target"),
        pytest.param(
            "[a]{tone=info [b](https://u.io)}",
            "[b](https://u.io)",
            "{tone=info [b](https://u.io)}",
            id="web-link",
        ),
        pytest.param(
            "[a]{tone=info [b](#method)}", "[b](#method)", "{tone=info [b](#method)}", id="anchor-link"
        ),
        pytest.param(
            "[a]{tone=info [b](u) `c`}", "[b](u)", "{tone=info [b](u) `c`}", id="link-and-a-code-span"
        ),
    ],
)
def test_markup_inside_an_attribute_list_is_a_malformed_attribute_named_as_written(
    text: str, attribute: str, token: str
) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(f"x {text} y", FULL_CONTEXT)

    assert str(raised.value) == (
        f"malformed attribute '{attribute}' in {token}: write each attribute as key=value, "
        "with no spaces around '='"
    )


def test_braces_holding_another_brace_are_no_attribute_list() -> None:
    assert parse_rich("x [a]{tone=info [b]{tone=danger}} y", FULL_CONTEXT) == (
        Plain("x [a]{tone=info "),
        Tinted("danger", None, (Plain("b"),)),
        Plain("} y"),
    )


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param(
            "[x](https://a.b/?q=[a]{tone=info})",
            (Link((Plain("x"),), "https://a.b/?q=[a]{tone=info}"),),
            id="span-syntax-inside-a-url",
        ),
        pytest.param(
            "[a](https://x/]{tone=info})",
            (Link((Plain("a"),), "https://x/]{tone=info}"),),
            id="stray-attribute-list-inside-a-url",
        ),
        pytest.param(
            "[[docs]{tone=info}](https://a.b/?q=[c]{bg=info})",
            (Link((Tinted("info", None, (Plain("docs"),)),), "https://a.b/?q=[c]{bg=info}"),),
            id="tinted-label-and-span-syntax-inside-the-url",
        ),
    ],
)
def test_a_link_url_is_never_read_as_an_attribute_span(text: str, runs: Rich) -> None:
    assert parse_rich(text, FULL_CONTEXT) == runs


def test_a_link_label_keeps_a_citation_and_a_code_span() -> None:
    assert parse_rich("[see `x` [^sop]](https://example.com/a)", FULL_CONTEXT) == (
        Link(
            (Plain("see "), Code("x"), Plain(" "), Citation("sop", 1, "https://example.com/sop")),
            "https://example.com/a",
        ),
    )


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        pytest.param(
            "[^sop](https://e.com)",
            (Citation("sop", 1, "https://example.com/sop"), Plain("(https://e.com)")),
            id="citation-then-parentheses",
        ),
        pytest.param(
            "[a $`x](u) `$",
            (Plain("[a "), InlineMath("x](u)")),
            id="math-that-runs-past-the-bracket-leaves-no-link",
        ),
    ],
)
def test_a_citation_or_math_span_takes_its_brackets_before_a_link(text: str, runs: Rich) -> None:
    assert parse_rich(text, FULL_CONTEXT) == runs


@pytest.mark.parametrize(
    ("text", "url"),
    [
        pytest.param("[a](<https://x.io/a b>)", "https://x.io/a b", id="angle-brackets-hold-a-space"),
        pytest.param("[a](https://x.io/é)", "https://x.io/é", id="non-ascii"),
        pytest.param("[a](https://x.io/a\\b)", "https://x.io/a\\b", id="backslash-before-a-letter"),
    ],
)
def test_a_link_url_reaches_the_writers_as_written(text: str, url: str) -> None:
    runs = parse_rich(text)

    assert (runs, write_runs(runs, _TaggedRuns())) == ((Link((Plain("a"),), url),), f"<link:a|{url}>")


@pytest.mark.parametrize(
    ("text", "context"),
    [
        pytest.param("[x](javascript:alert(1))", FULL_CONTEXT, id="disallowed-scheme"),
        pytest.param("[x](javascript:alert('http://e.com'))", FULL_CONTEXT, id="allowed-scheme-inside-a-url"),
        pytest.param("[x](ftp://h/?u=https://y.io)", FULL_CONTEXT, id="allowed-scheme-in-a-query"),
        pytest.param("[x](data:text/html,#a)", FULL_CONTEXT, id="anchor-inside-a-data-url"),
        pytest.param("[x]()", FULL_CONTEXT, id="empty-url"),
        pytest.param("[](https://a.io)", FULL_CONTEXT, id="empty-label"),
        pytest.param('[x](https://a.io "t")', FULL_CONTEXT, id="link-title"),
        pytest.param("![alt](https://e.com/i.png)", FULL_CONTEXT, id="image"),
        pytest.param("![**b** [^sop]](https://e.com/i.png)", FULL_CONTEXT, id="image-with-marks-in-its-alt"),
        pytest.param("{tone=info} [unclosed", FULL_CONTEXT, id="attribute-list-then-an-unclosed-bracket"),
        pytest.param("{tone=info}[a", FULL_CONTEXT, id="attribute-list-then-an-unclosed-label"),
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


@pytest.mark.parametrize("target", ["#method`y`", "#method[^sop]"])
def test_an_anchor_link_target_is_read_as_written_and_fails_when_no_heading_has_it(target: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(f"[x]({target})", FULL_CONTEXT)

    assert str(raised.value) == (
        f"rich text links to unknown anchor '{target}' — no heading or section has that id"
    )


@pytest.mark.parametrize("token", ["{{a.b}}", "{{two words}}", "{{}}"])
def test_a_malformed_placeholder_fails_naming_it(token: str) -> None:
    with pytest.raises(ReportError, match=rf"invalid placeholder '{re.escape(token)}'"):
        parse_rich(f"a {token} b")


@pytest.mark.parametrize(
    ("text", "token"),
    [
        pytest.param("wrap {{ `code` }} it", "{{`code`}}", id="code-span"),
        pytest.param("wrap {{[x](https://y.com)}} it", "{{[x](https://y.com)}}", id="link"),
    ],
)
def test_a_placeholder_wrapped_around_other_markup_fails_naming_it_as_written(text: str, token: str) -> None:
    with pytest.raises(ReportError) as raised:
        parse_rich(text)

    assert str(raised.value) == (
        f"invalid placeholder '{token}': a placeholder name is letters, digits, '_' or '-' only "
        "(a fill-me-later blank is written {{name}}; for a literal {{ use a `code` span)"
    )


@pytest.mark.parametrize(
    ("marker", "shown"),
    [
        pytest.param("\x00", "\N{REPLACEMENT CHARACTER}", id="nul-becomes-the-replacement-character"),
        pytest.param("\x01", "\x01", id="start-of-heading-stays"),
    ],
)
def test_control_characters_follow_commonmark(marker: str, shown: str) -> None:
    assert parse_rich(f"a{marker}b **c** [d](https://e.com) {marker}0{marker}") == (
        Plain(f"a{shown}b "),
        Styled("bold", (Plain("c"),)),
        Plain(" "),
        Link((Plain("d"),), "https://e.com"),
        Plain(f" {shown}0{shown}"),
    )


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
