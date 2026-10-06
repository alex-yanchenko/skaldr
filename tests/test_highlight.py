from html.parser import HTMLParser
from typing import Any

import pytest

from skaldr.models import parse_report
from skaldr.render import render_html
from tests.factories.report_factory import make_report


def code_panel(**block: Any) -> str:
    html = render_html(parse_report(make_report(blocks=[{"type": "code", **block}])))
    start = html.index('<div class="code">')
    end = html.index("</pre></div>", start) + len("</pre></div>")
    return html[start:end]


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
    class Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    source = 'def f(x):\n    return "a<&b"  # </script>\n'
    reader = Text()
    reader.feed(code_panel(content=source, lang="python"))
    assert "".join(reader.parts) == source


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
