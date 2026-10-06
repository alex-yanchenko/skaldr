import time
from collections.abc import Iterator
from html.parser import HTMLParser
from typing import cast

import pytest
from markupsafe import Markup
from pygments.lexer import Lexer
from pygments.token import Keyword, Text, _TokenType  # pyright: ignore[reportPrivateUsage]

from skaldr import highlight
from skaldr.models import parse_report
from skaldr.render import render_html
from tests.factories.report_factory import make_report


def code_panel(**block: str) -> str:
    html = render_html(parse_report(make_report(blocks=[{"type": "code", **block}])))
    start = html.index('<div class="code">')
    end = html.index("</pre></div>", start) + len("</pre></div>")
    return html[start:end]


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def visible_text(markup: str) -> str:
    reader = VisibleText()
    reader.feed(markup)
    return "".join(reader.parts)


PYTHON_SNIPPET = 'def f(x): return "a<&b"'
HIGHLIGHTED_PYTHON_SNIPPET = (
    '<span class="t-kw">def</span> <span class="t-fn">f</span><span class="t-pun">(</span>x'
    '<span class="t-pun">):</span> <span class="t-kw">return</span> '
    '<span class="t-str">&#34;a&lt;&amp;b&#34;</span>'
)


def test_a_known_language_is_highlighted_with_short_token_classes() -> None:
    assert code_panel(content=PYTHON_SNIPPET, lang="python") == (
        f'<div class="code"><pre>{HIGHLIGHTED_PYTHON_SNIPPET}</pre></div>'
    )


def test_a_file_name_label_picks_the_language_when_lang_is_missing() -> None:
    assert code_panel(content=PYTHON_SNIPPET, label="tool.py") == (
        '<div class="code"><div class="code-label">tool.py</div>'
        f"<pre>{HIGHLIGHTED_PYTHON_SNIPPET}</pre></div>"
    )


def test_lang_wins_over_the_language_the_label_names() -> None:
    assert code_panel(content="x = 1", label="tool.py", lang="plain text") == (
        '<div class="code"><div class="code-label">tool.py</div><pre>x = 1</pre></div>'
    )


@pytest.mark.parametrize(
    "block",
    [
        pytest.param({"content": "a < b && c"}, id="no-language"),
        pytest.param({"content": "a < b && c", "lang": "no-such-language"}, id="unknown-lang"),
        pytest.param({"content": "a < b && c", "label": "notes.zzz"}, id="unknown-suffix"),
    ],
)
def test_code_without_a_usable_language_renders_plain_and_escaped(block: dict[str, str]) -> None:
    assert code_panel(**block).endswith("<pre>a &lt; b &amp;&amp; c</pre></div>")


def test_every_token_kind_the_page_styles_gets_its_own_class() -> None:
    source = 'class A:\n    def m(self): return 1 + 2.5  # note\n    s = "x"\n'
    assert code_panel(content=source, lang="python") == (
        '<div class="code"><pre><span class="t-kw">class</span> <span class="t-cls">A</span>'
        '<span class="t-pun">:</span>\n'
        '    <span class="t-kw">def</span> <span class="t-fn">m</span><span class="t-pun">(</span>self'
        '<span class="t-pun">):</span> <span class="t-kw">return</span> <span class="t-num">1</span> '
        '<span class="t-op">+</span> <span class="t-num">2.5</span>  <span class="t-com"># note</span>\n'
        '    s <span class="t-op">=</span> <span class="t-str">&#34;x&#34;</span>\n</pre></div>'
    )


def test_a_trailing_newline_is_not_added_or_dropped() -> None:
    assert code_panel(content="x = 1", lang="python").endswith(
        'x <span class="t-op">=</span> <span class="t-num">1</span></pre></div>'
    )


def test_a_multi_line_string_keeps_its_tokens_inside_each_line() -> None:
    assert code_panel(content='s = """a\nb"""', lang="python") == (
        '<div class="code"><pre>s <span class="t-op">=</span> <span class="t-str">&#34;&#34;&#34;a</span>\n'
        '<span class="t-str">b&#34;&#34;&#34;</span></pre></div>'
    )


def test_diff_mode_highlights_each_line_in_the_language_and_keeps_the_markers() -> None:
    content = "+x = 1\n-x = 2\n x = 3"
    assert code_panel(content=content, mode="diff", lang="python") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln add">x <span class="t-op">=</span> <span class="t-num">1</span></span>'
        '<span class="ln del">x <span class="t-op">=</span> <span class="t-num">2</span></span>'
        '<span class="ln ctx"> x <span class="t-op">=</span> <span class="t-num">3</span></span>'
        "</pre></div>"
    )


def test_diff_mode_without_a_language_stays_plain_and_escaped() -> None:
    assert code_panel(content="+a < b\n-c", mode="diff") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln add">a &lt; b</span><span class="ln del">c</span>'
        "</pre></div>"
    )


def test_a_closing_script_tag_in_highlighted_code_is_escaped() -> None:
    html = code_panel(content='x = "</script><b>"', lang="python")
    assert "</script>" not in html
    assert "&lt;/script&gt;&lt;b&gt;" in html


def test_a_closing_script_tag_in_unhighlighted_code_is_escaped() -> None:
    assert "</script>" not in code_panel(content="</script>")


def test_copied_text_is_the_plain_code() -> None:
    source = 'def f(x):\n    return "a<&b"  # </script>\n'
    assert visible_text(code_panel(content=source, lang="python")) == source


@pytest.mark.parametrize("newline", ["\r\n", "\r"], ids=["crlf", "lone-cr"])
def test_carriage_returns_in_highlighted_code_become_line_feeds(newline: str) -> None:
    assert code_panel(content=f"x = 1{newline}y = 2", lang="python") == (
        '<div class="code"><pre>x <span class="t-op">=</span> <span class="t-num">1</span>\n'
        'y <span class="t-op">=</span> <span class="t-num">2</span></pre></div>'
    )


def test_a_lone_carriage_return_in_a_highlighted_diff_starts_a_context_line() -> None:
    assert code_panel(content="+a\rb\n c", mode="diff", lang="python") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln add">a</span><span class="ln ctx">b</span><span class="ln ctx"> c</span>'
        "</pre></div>"
    )


def test_crlf_in_a_highlighted_diff_does_not_change_the_line_count() -> None:
    assert code_panel(content="+x = 1\r\n y = 2", mode="diff", lang="python") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln add">x <span class="t-op">=</span> <span class="t-num">1</span></span>'
        '<span class="ln ctx"> y <span class="t-op">=</span> <span class="t-num">2</span></span>'
        "</pre></div>"
    )


def test_unstyled_tokens_are_escaped() -> None:
    assert code_panel(content="echo <img src=x onerror=1> &amp; </script>", lang="bash") == (
        '<div class="code"><pre>echo &lt;img src<span class="t-op">=</span>x '
        'onerror<span class="t-op">=</span><span class="t-num">1</span>&gt; '
        '<span class="t-pun">&amp;</span>amp<span class="t-pun">;</span> '
        "&lt;/script&gt;</pre></div>"
    )


def test_a_string_opened_on_a_removed_line_does_not_colour_the_added_side() -> None:
    assert code_panel(content='-s = """\n+s = 1\n print(s)', mode="diff", lang="python") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln del">s <span class="t-op">=</span> <span class="t-str">&#34;&#34;&#34;</span></span>'
        '<span class="ln add">s <span class="t-op">=</span> <span class="t-num">1</span></span>'
        '<span class="ln ctx"> print<span class="t-pun">(</span>s<span class="t-pun">)</span></span>'
        "</pre></div>"
    )


def test_code_over_the_size_cap_renders_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skaldr.highlight.MAX_HIGHLIGHTED_CHARACTERS", 5)
    assert code_panel(content="x = 12", lang="python") == '<div class="code"><pre>x = 12</pre></div>'


def test_a_diff_over_the_size_cap_renders_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skaldr.highlight.MAX_HIGHLIGHTED_CHARACTERS", 5)
    assert code_panel(content="+x = 1\n y", mode="diff", lang="python") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln add">x = 1</span><span class="ln ctx"> y</span>'
        "</pre></div>"
    )


def test_code_at_the_size_cap_is_still_highlighted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skaldr.highlight.MAX_HIGHLIGHTED_CHARACTERS", 5)
    assert code_panel(content="x = 1", lang="python") == (
        '<div class="code"><pre>x <span class="t-op">=</span> <span class="t-num">1</span></pre></div>'
    )


def test_the_size_cap_counts_the_text_after_line_endings_are_normalised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("skaldr.highlight.MAX_HIGHLIGHTED_CHARACTERS", 5)
    assert code_panel(content="x=1\r\ny", lang="python") == (
        '<div class="code"><pre>x<span class="t-op">=</span><span class="t-num">1</span>\ny</pre></div>'
    )


def test_a_console_line_without_a_trailing_newline_is_kept() -> None:
    assert code_panel(content="$ ls", lang="console") == '<div class="code"><pre>$ ls</pre></div>'


def test_the_last_console_line_without_a_trailing_newline_is_kept() -> None:
    assert code_panel(content="$ ls -l\ntotal 0", lang="console") == (
        '<div class="code"><pre>$ ls -l\ntotal 0</pre></div>'
    )


def test_a_console_diff_keeps_its_context_line() -> None:
    assert code_panel(content="+$ ls\n x", mode="diff", lang="console") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln add">$ ls</span><span class="ln ctx"> x</span>'
        "</pre></div>"
    )


@pytest.mark.parametrize(
    "language",
    [
        "console",
        "shell-session",
        "rconsole",
        "ps1con",
        "doscon",
        "tcshcon",
        "sqlite3",
        "rbcon",
        "pwsh-session",
        "psysh",
    ],
)
def test_session_lexers_never_drop_the_text_of_the_block(language: str) -> None:
    source = "$ one\ntwo\n> three"
    assert visible_text(code_panel(content=source, lang=language)) == source


def test_a_lexer_that_expands_tabs_renders_the_block_plain() -> None:
    source = "*** Test Cases ***\nCase\n\tLog\tx"
    assert code_panel(content=source, lang="robotframework") == (
        f'<div class="code"><pre>{source}</pre></div>'
    )


def test_a_leading_byte_order_mark_is_kept() -> None:
    assert (
        code_panel(content="\ufeffx = 1", lang="python") == '<div class="code"><pre>\ufeffx = 1</pre></div>'
    )


def test_a_lone_carriage_return_in_a_plain_block_becomes_a_line_feed() -> None:
    assert code_panel(content="a\rb") == '<div class="code"><pre>a\nb</pre></div>'


def test_a_lone_carriage_return_in_a_plain_diff_added_line_starts_a_context_line() -> None:
    assert code_panel(content="+a\rb", mode="diff") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln add">a</span><span class="ln ctx">b</span>'
        "</pre></div>"
    )


def test_diff_context_lines_are_lexed_without_their_marker_column() -> None:
    assert code_panel(content="-a:\n+  b: 1\n   c: 2", mode="diff", lang="yaml") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln del">a<span class="t-pun">:</span></span>'
        '<span class="ln add">  b<span class="t-pun">:</span> 1</span>'
        '<span class="ln ctx">   c<span class="t-pun">:</span> 2</span>'
        "</pre></div>"
    )


def test_diff_context_indentation_matches_the_added_side() -> None:
    assert code_panel(content="+if a:\n+    b = 1\n     c = 2", mode="diff", lang="python") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln add"><span class="t-kw">if</span> a<span class="t-pun">:</span></span>'
        '<span class="ln add">    b <span class="t-op">=</span> <span class="t-num">1</span></span>'
        '<span class="ln ctx">     c <span class="t-op">=</span> <span class="t-num">2</span></span>'
        "</pre></div>"
    )


@pytest.mark.parametrize(
    ("content", "rows"),
    [
        pytest.param(
            "+a = 1\n+b = 2",
            '<span class="ln add">a <span class="t-op">=</span> <span class="t-num">1</span></span>'
            '<span class="ln add">b <span class="t-op">=</span> <span class="t-num">2</span></span>',
            id="only-added",
        ),
        pytest.param(
            "-a = 1\n-b = 2",
            '<span class="ln del">a <span class="t-op">=</span> <span class="t-num">1</span></span>'
            '<span class="ln del">b <span class="t-op">=</span> <span class="t-num">2</span></span>',
            id="only-removed",
        ),
        pytest.param(
            "+a = 1\n\n-b = 2",
            '<span class="ln add">a <span class="t-op">=</span> <span class="t-num">1</span></span>'
            '<span class="ln ctx"></span>'
            '<span class="ln del">b <span class="t-op">=</span> <span class="t-num">2</span></span>',
            id="blank-context-line",
        ),
        pytest.param(
            "+a = 1\n",
            '<span class="ln add">a <span class="t-op">=</span> <span class="t-num">1</span></span>'
            '<span class="ln ctx"></span>',
            id="trailing-newline",
        ),
    ],
)
def test_highlighted_diff_shapes(content: str, rows: str) -> None:
    assert code_panel(content=content, mode="diff", lang="python") == (
        f'<div class="code"><pre class="diff">{rows}</pre></div>'
    )


def test_unprefixed_diff_context_lines_are_lexed_whole() -> None:
    assert code_panel(content="def f():\n-    return 1\n+    return 2", mode="diff", lang="python") == (
        '<div class="code"><pre class="diff">'
        '<span class="ln ctx"><span class="t-kw">def</span> <span class="t-fn">f</span>'
        '<span class="t-pun">():</span></span>'
        '<span class="ln del">    <span class="t-kw">return</span> <span class="t-num">1</span></span>'
        '<span class="ln add">    <span class="t-kw">return</span> <span class="t-num">2</span></span>'
        "</pre></div>"
    )


def test_unprefixed_typescript_diff_context_keeps_its_first_character() -> None:
    panel = code_panel(
        content="function pick(a) {\n-  return 1;\n+  return 2;\n}", mode="diff", lang="typescript"
    )
    assert visible_text(panel) == "function pick(a) {  return 1;  return 2;}"
    assert '<span class="ln ctx"><span class="t-kw">function</span> pick' in panel


def test_a_hunk_header_context_line_keeps_its_first_character() -> None:
    panel = code_panel(content="@@ -1 +1 @@\n-x = 1\n+x = 2", mode="diff", lang="python")
    assert visible_text(panel) == "@@ -1 +1 @@x = 1x = 2"


def stub_lexer(*tokens: tuple[_TokenType, str]) -> Lexer:
    class Stub:
        def get_tokens(self, _text: str) -> Iterator[tuple[_TokenType, str]]:
            return iter(tokens)

    return cast(Lexer, Stub())


def test_the_fidelity_guard_accepts_tokens_that_rebuild_the_text() -> None:
    assert highlight.lexed_lines("ab", stub_lexer((Keyword, "a"), (Text, "b\n"))) == [
        Markup('<span class="t-kw">a</span>b')
    ]


def test_the_fidelity_guard_refuses_a_lexer_that_drops_text() -> None:
    assert highlight.lexed_lines("ab\n", stub_lexer((Text, "a\n"))) is None


def test_the_fidelity_guard_refuses_a_lexer_that_reorders_text() -> None:
    assert highlight.lexed_lines("ab\n", stub_lexer((Text, "b"), (Keyword, "a"), (Text, "\n"))) is None


@pytest.mark.parametrize(
    ("language", "snippet"),
    [
        ("python", "def f(x): return 1"),
        ("javascript", "const a = 1;"),
        ("typescript", "const a: number = 1;"),
        ("sql", "SELECT 1 FROM t;"),
        ("yaml", "a: 1\nb: [1]"),
        ("json", '{"a": 1}'),
        ("bash", 'if [ -f x ]; then echo "a"; fi'),
        ("go", "func main() { return 1 }"),
        ("rust", "fn main() { let x = 1; }"),
        ("java", "class A { int x = 1; }"),
        ("ruby", "def f; 1; end"),
        ("html", '<a href="x">y</a>'),
        ("css", "a { color: red; }"),
        ("markdown", "# Title\n**b** `c`"),
        ("dockerfile", 'FROM python:3\nRUN echo "x"'),
        ("toml", "[a]\nb = 1"),
    ],
)
def test_common_languages_are_highlighted_and_keep_their_text(language: str, snippet: str) -> None:
    panel = code_panel(content=snippet, lang=language)
    assert 'class="t-' in panel
    assert visible_text(panel) == snippet


@pytest.mark.parametrize(("language", "unit"), [("perl", "<<"), ("rust", 'r#"')])
def test_a_pathological_block_at_the_size_cap_renders_within_a_bound(language: str, unit: str) -> None:
    content = unit * (highlight.MAX_HIGHLIGHTED_CHARACTERS // len(unit))
    started = time.perf_counter()
    panel = code_panel(content=content, lang=language)
    assert time.perf_counter() - started < 3
    assert visible_text(panel) == content
