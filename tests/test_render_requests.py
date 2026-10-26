import re
import subprocess
from html import unescape
from pathlib import Path
from typing import Any

import pytest

from skaldr import compute
from skaldr.errors import ReportError
from skaldr.models import MAX_STRIP_LABELS, Request, package_path, parse_report
from skaldr.render import find_placeholders, placeholder_locations, render_html
from tests.factories import (
    make_command_request,
    make_flow,
    make_query_request,
    make_report,
    make_request,
    make_step,
    make_tab,
    make_tabs,
    make_toggle,
)
from tests.factories.render_factory import container_rules, inline_scripts, script_hash, strip_rail_rules


def test_a_tabs_block_writes_the_request_tab_strip_around_its_panes() -> None:
    block = make_tabs(
        make_tab("Floor", {"type": "text", "body": "Recount."}, tone="warning"),
        make_tab("System", {"type": "text", "body": "Rescan."}),
    )

    html = render_html(parse_report(make_report(blocks=[block])))

    assert (
        '<div class="tabs"><div class="tab-cases tb0" role="group" aria-label="Tabs">\n'
        '<input type="radio" class="tab-pick" name="tb0" id="tb0_0" checked>\n'
        '<section class="tab-pane">\n<h4 class="tab-pane-hd">Floor</h4>\n'
        '<p class="text">Recount.</p></section>\n'
        '<input type="radio" class="tab-pick" name="tb0" id="tb0_1">\n'
        '<section class="tab-pane">\n<h4 class="tab-pane-hd">System</h4>\n'
        '<p class="text">Rescan.</p></section>\n'
        '<div class="tab-list"><label for="tb0_0"><span class="tab-dot warning"></span>Floor</label>'
        '<label for="tb0_1">System</label></div>\n'
        "</div>\n</div>"
    ) in html


def test_tab_blocks_and_requests_never_share_a_radio_group() -> None:
    nested = make_tabs(make_tab("Inner"), make_tab("Other"))
    outer = make_tabs(make_tab("Outer", nested), make_tab("Second", {"type": "divider"}))
    request = make_command_request(
        cases=[{"label": "a", "response": {"body": "x"}}, {"label": "b", "response": {"body": "y"}}]
    )

    html = render_html(parse_report(make_report(blocks=[outer, request])))

    assert re.findall(r'class="tab-pick" name="([^"]+)"', html) == ["tb0", "tb1", "tb1", "tb0", "rq0", "rq0"]


def test_a_request_strip_still_turns_into_a_rail_at_the_width_its_case_labels_need() -> None:
    html = render_html(parse_report(_request_report()))

    assert container_rules(html) == [(compute.strip_width(["widgets", "admin"]), strip_rail_rules("rq0"))]


def test_a_request_inside_a_section_toggle_gets_its_radio_group_rail_and_runtime() -> None:
    cases = [{"label": "a", "response": {"body": "x"}}, {"label": "b", "response": {"body": "y"}}]
    section = {"type": "section", "title": "S", "blocks": [make_toggle(make_command_request(cases=cases))]}

    html = render_html(parse_report(make_report(blocks=[section])))

    assert (
        re.findall(r'class="tab-pick" name="([^"]+)" id="([^"]+)"', html),
        container_rules(html),
        "data-rq-slot" in _request_runtime_script(html),
    ) == (
        [("rq0", "rq0_0"), ("rq0", "rq0_1")],
        [(compute.strip_width(["a", "b"]), strip_rail_rules("rq0"))],
        True,
    )


def _request_report(**overrides: object) -> dict[str, object]:
    block: dict[str, object] = {
        "type": "request",
        "label": "Read an endpoint",
        "method": "GET",
        "url": "https://{{host}}/{{resource}}",
        "headers": {"Authorization": "Bearer {{token}}", "Accept": "application/json"},
        "variables": [{"name": "host", "example": "api.example.com"}, {"name": "token", "secret": True}],
        "case_variable": "resource",
        "cases": [
            {"label": "widgets", "response": {"status": 200, "body": "[]"}, "verdict": "Open data."},
            {"label": "admin", "headers": {}, "response": {"status": 401, "body": "{}"}},
        ],
    }
    block.update(overrides)
    return make_report(blocks=[block])


def test_a_request_renders_a_slot_per_variable_and_an_input_to_fill_it() -> None:
    html = render_html(parse_report(_request_report()))

    assert 'data-rq-var="host"' in html
    assert 'data-rq-slot="host"' in html
    assert 'value="api.example.com"' in html


def test_a_secret_variable_offers_its_example_as_a_hint_but_never_as_a_value() -> None:
    variables = [
        {"name": "host", "example": "api.example.com"},
        {"name": "token", "secret": True, "example": "paste your own"},
    ]

    html = render_html(parse_report(_request_report(variables=variables)))
    field = html.split('data-rq-var="token"')[1].split(">")[0]

    assert 'placeholder="paste your own"' in field
    assert "value=" not in field


def test_the_case_axis_resolves_at_build_time_and_reader_tokens_stay_open() -> None:
    html = render_html(parse_report(_request_report()))

    assert 'data-rq-slot="resource"' not in html
    assert "/widgets" in html
    assert 'data-rq-slot="host"' in html


def test_a_case_may_replace_the_requests_headers() -> None:
    html = render_html(parse_report(_request_report()))
    cases = html.split('data-rq-case="')

    assert "Authorization" in cases[1]
    assert "Authorization" not in cases[2]


def test_a_secret_fills_the_command_like_any_other_field() -> None:
    """A secret is a slot the page substitutes, so the command a reader copies runs as it stands."""
    variables = [
        {"name": "host", "example": "api.example.com"},
        {"name": "token", "secret": True},
    ]
    html = render_html(parse_report(_request_report(variables=variables)))
    command = html.split('class="rq-cmd"')[1].split("</pre>")[0]

    assert 'data-rq-slot="token"' in command
    assert "$TOKEN" not in command


def test_only_a_field_that_is_not_secret_is_kept_across_a_reload() -> None:
    """sessionStorage dies with the tab and never reaches disk, and a secret field carries no key at
    all, so nothing a reader treats as a credential is written even there."""
    variables = [
        {"name": "host", "example": "api.example.com"},
        {"name": "token", "secret": True},
    ]

    html = render_html(parse_report(_request_report(variables=variables)))

    assert re.findall(r'data-rq-keep="([^"]+)"', html) == ["Read an endpoint:host"]


def test_a_response_header_that_repeats_renders_every_value() -> None:
    case = {
        "label": "widgets",
        "response": {"status": 200, "headers": {"set-cookie": ["a=1", "b=2"]}, "body": "[]"},
    }

    html = render_html(
        parse_report(_request_report(cases=[case], case_variable=None, url="https://{{host}}/x"))
    )

    assert "a=1\nb=2" in html


def test_every_case_stays_in_the_document_so_print_can_show_them_all() -> None:
    """Selection hides a case with `display`, never by leaving it out, so print can show them all."""
    html = render_html(parse_report(_request_report()))

    assert html.count('data-rq-case="') == 2
    assert html.count('type="radio" class="tab-pick"') == 2
    assert html.count(" checked>") == 1


def test_inline_scripts_are_collected_whatever_their_attributes_and_the_yaml_source_is_skipped() -> None:
    html = (
        '<script>a()</script><script type="module">b()</script><script defer>c()</script>'
        '<script type="application/yaml" id="skaldr-source">d: 1</script><script></script>'
    )

    assert inline_scripts(html) == ["a()", "b()", "c()", ""]


def _request_runtime_script(html: str) -> str:
    return next(script for script in inline_scripts(html) if "data-rq-slot" in script)


def _cases(count: int) -> list[dict[str, object]]:
    return [{"label": f"case-{number}", "response": {"status": 200, "body": "[]"}} for number in range(count)]


@pytest.mark.parametrize("count", [2, 6, 7, 15])
def test_every_case_carries_a_label_whatever_the_count(count: int) -> None:
    """One treatment at every size: the strip holds every case and the container query decides whether
    it sits on a line or stacks, so the count never changes what is rendered."""
    html = render_html(parse_report(_request_report(cases=_cases(count), case_variable="resource")))

    assert html.count("<label for=") == count
    assert html.count('class="tab-list"') == 1


def _tabbed_flow() -> dict[str, object]:
    steps = [
        make_step(captures=[{"name": "token", "source": "body"}]),
        make_step(
            url="https://{{host}}/{{resource}}",
            headers={"Authorization": "Bearer {{token}}"},
            case_variable="resource",
            cases=[
                {"label": "widgets", "response": {"status": 200, "body": "[]"}},
                {"label": "gadgets", "response": {"status": 200, "body": "[]"}},
                {"label": "sprockets", "response": {"status": 403, "body": "{}"}},
            ],
        ),
    ]
    return make_report(blocks=[make_flow(steps=steps)])


def test_a_variable_used_only_in_headers_add_counts_as_used() -> None:
    """The scan behind every variable check reads the url, the headers, the body, a case's `headers`
    replacement and its `headers_add` layer alike, because all of them are interpolated the same way."""
    report = _request_report(
        url="https://api.example.com/x",
        headers={"Authorization": "Bearer {{token}}"},
        variables=[{"name": "token", "secret": True}, {"name": "trace", "example": "abc"}],
        case_variable=None,
        cases=[
            {
                "label": "traced",
                "headers_add": {"X-Trace": "{{trace}}"},
                "response": {"status": 200, "body": "[]"},
            }
        ],
    )

    block = parse_report(report).blocks[0]
    assert isinstance(block, Request)

    assert block.referenced_variables() == {"token", "trace"}


def test_an_undeclared_variable_in_headers_add_still_fails_strict() -> None:
    """The other direction of the same scan: a name that lives only in `headers_add` and matches no
    declared variable is an unfilled placeholder, which is what the finalize gate exists to catch."""
    report = _request_report(
        url="https://api.example.com/x",
        headers={"Authorization": "Bearer {{token}}"},
        variables=[{"name": "token", "secret": True}],
        case_variable=None,
        cases=[
            {
                "label": "typo",
                "headers_add": {"X-Trace": "{{tokne}}"},
                "response": {"status": 200, "body": "[]"},
            }
        ],
    )

    assert find_placeholders(parse_report(report)) == ["tokne"]


def test_headers_add_replaces_a_name_whatever_case_it_is_written_in() -> None:
    """Header names are case-insensitive on the wire, so `content-type` names the same header as
    `Content-Type`. Matching them by exact string would send both, and a reader pasting that command
    gets two conflicting values rather than the one the case states. The request's own spelling is
    what renders, so the case reads as an override of it."""
    report = _request_report(
        url="https://api.example.com/x",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        variables=[],
        case_variable=None,
        cases=[
            {
                "label": "plain",
                "headers_add": {"content-type": "text/plain"},
                "response": {"status": 200, "body": "[]"},
            }
        ],
    )
    block = parse_report(report).blocks[0]
    assert isinstance(block, Request)

    assert compute.request_headers(block, block.cases[0]) == {
        "Content-Type": "text/plain",
        "Accept": "application/json",
    }


def test_the_headers_a_case_sends_are_its_own_to_hold() -> None:
    """`block.headers` is shared by every case that sets none of its own, so handing a caller the
    model's dict would let one case's reader mutate what the next one sends."""
    report = _request_report(
        url="https://api.example.com/x",
        headers={"Accept": "application/json"},
        variables=[],
        case_variable=None,
    )
    block = parse_report(report).blocks[0]
    assert isinstance(block, Request)

    first = compute.request_headers(block, block.cases[0])
    first["X-Injected"] = "1"

    assert compute.request_headers(block, block.cases[0]) == {"Accept": "application/json"}


def test_headers_add_appends_a_name_the_request_does_not_set() -> None:
    """A name the request has no spelling of is added after the ones it does, so the request's own
    header order survives and the case's additions read as additions."""
    report = _request_report(
        url="https://api.example.com/x",
        headers={"Accept": "application/json"},
        variables=[],
        case_variable=None,
        cases=[
            {
                "label": "traced",
                "headers_add": {"accept": "text/plain", "X-Trace": "1"},
                "response": {"status": 200, "body": "[]"},
            }
        ],
    )
    block = parse_report(report).blocks[0]
    assert isinstance(block, Request)

    assert list(compute.request_headers(block, block.cases[0]).items()) == [
        ("Accept", "text/plain"),
        ("X-Trace", "1"),
    ]


def test_headers_add_layers_over_the_requests_headers() -> None:
    """Cases that share an auth header and differ in one other name write the shared one once, on the
    request, and only the difference per case."""
    report = _request_report(
        headers={"Authorization": "Bearer {{token}}", "Accept": "application/json"},
        cases=[
            {
                "label": "v1",
                "headers_add": {"Accept": "application/vnd.example.v1+json"},
                "response": {"status": 200, "body": "[]"},
            },
            {"label": "plain", "response": {"status": 200, "body": "[]"}},
        ],
    )
    block = parse_report(report).blocks[0]
    assert isinstance(block, Request)

    assert compute.request_headers(block, block.cases[0]) == {
        "Authorization": "Bearer {{token}}",
        "Accept": "application/vnd.example.v1+json",
    }
    assert compute.request_headers(block, block.cases[1]) == {
        "Authorization": "Bearer {{token}}",
        "Accept": "application/json",
    }


def test_headers_add_refuses_to_share_a_case_with_headers() -> None:
    """`headers` replaces and `headers_add` layers, so a case setting both states its headers twice and
    leaves a reader guessing which wins. Whatever it meant is already expressible with `headers` alone."""
    report = _request_report(
        cases=[
            {
                "label": "both",
                "headers": {"Accept": "application/json"},
                "headers_add": {"X-Trace": "1"},
                "response": {"status": 200, "body": "[]"},
            }
        ],
        case_variable=None,
        url="https://{{host}}/x",
    )

    with pytest.raises(ReportError, match="headers replaces and headers_add layers"):
        parse_report(report)


def test_an_emptied_headers_map_still_sends_none() -> None:
    """An empty `headers` map sends no headers at all, which is how a case records the result with the
    auth header removed. `headers` replaces; only `headers_add` layers."""
    report = _request_report(
        cases=[{"label": "no auth", "headers": {}, "response": {"status": 401, "body": "{}"}}],
        case_variable=None,
        url="https://{{host}}/x",
    )
    block = parse_report(report).blocks[0]
    assert isinstance(block, Request)

    assert compute.request_headers(block, block.cases[0]) == {}


@pytest.mark.parametrize(
    ("labels", "width"),
    [
        pytest.param(["ok"], 87, id="one-short"),
        pytest.param(["ok", "no"], 142, id="two-short"),
        pytest.param(["a" * 20], 229, id="one-long"),
    ],
)
def test_the_width_a_strip_asks_for_is_read_off_its_labels(labels: list[str], width: int) -> None:
    """The threshold a block switches at, pinned to the value rather than its direction. Every part of
    it moves the answer: the per-character advance, the room a dot and the padding take, the slack for
    a wider fallback face, and the container's own padding."""
    assert compute.strip_width(labels) == width


def test_the_case_cap_matches_the_selectors_the_stylesheet_writes() -> None:
    """Highlighting the chosen label is the one thing needing a positional selector, and the stylesheet
    writes a fixed number of them. A cap above that count renders a case whose label never lights up
    and which the strip cannot select; a cap below it refuses a case the stylesheet would have served."""
    css = package_path("styles.css").read_text(encoding="utf-8")

    assert css.count(".tab-pick:nth-of-type(") == MAX_STRIP_LABELS
    assert f":nth-of-type({MAX_STRIP_LABELS}):checked" in css
    assert f":nth-of-type({MAX_STRIP_LABELS + 1}):checked" not in css


def test_the_case_cap_is_refused_one_past_its_edge() -> None:
    at_cap = _request_report(cases=_cases(MAX_STRIP_LABELS), case_variable="resource")
    over = _request_report(cases=_cases(MAX_STRIP_LABELS + 1), case_variable="resource")

    assert parse_report(at_cap) is not None
    with pytest.raises(ReportError, match=rf"records at most {MAX_STRIP_LABELS} cases"):
        parse_report(over)


def test_a_strip_too_wide_for_its_container_becomes_a_rail() -> None:
    """Whether a strip fits is a question about rendered width, and the count of cases is only a proxy
    for it. The labels are monospace, so their width is predictable at build time: each block carries
    a container query at the width its own labels need, and below that the strip stacks into a rail."""
    html = render_html(parse_report(_request_report(cases=_cases(12), case_variable="resource")))
    rules = re.findall(r"@container \(width < (\d+)px\)", html)

    assert len(rules) == 1
    assert int(rules[0]) > 400
    assert ".rq0 > .tab-list{flex-direction:column" in html


def test_each_block_gets_the_breakpoint_its_own_labels_need() -> None:
    """One threshold for the page would switch a short strip at a width it still fits, or leave a long
    one wrapping past the width it stopped fitting."""

    def block(count: int, label: str) -> dict[str, object]:
        return {
            "type": "request",
            "label": label,
            "method": "GET",
            "url": "https://api.example.com/{{resource}}",
            "case_variable": "resource",
            "cases": _cases(count),
        }

    html = render_html(parse_report(make_report(blocks=[block(3, "Short"), block(14, "Long")])))
    widths = [int(w) for w in re.findall(r"@container \(width < (\d+)px\)", html)]

    assert len(widths) == 2
    assert widths[0] < widths[1]


def test_a_single_case_needs_no_breakpoint_at_all() -> None:
    report = _request_report(
        cases=[{"label": "only", "response": {"status": 200, "body": "[]"}}],
        case_variable=None,
        url="https://{{host}}/x",
    )

    assert "@container" not in render_html(parse_report(report))


def test_choosing_a_case_needs_no_script() -> None:
    """A radio per case, its label in the strip, and the pane immediately after it, so `:checked +`
    shows one without an index to keep in step. The strip floats above the panes on flex order."""
    html = render_html(parse_report(_request_report()))
    script = _request_runtime_script(html)

    assert html.count('type="radio" class="tab-pick"') == 2
    assert 'class="tab-pick" name=' in html
    assert "data-rq-tab" not in html
    assert "data-rq-tab" not in script
    assert "aria-selected" not in script


def test_one_case_needs_no_strip_but_still_renders() -> None:
    report = _request_report(
        cases=[{"label": "only", "response": {"status": 200, "body": "[]"}}],
        case_variable=None,
        url="https://{{host}}/x",
    )
    html = render_html(parse_report(report))

    assert 'class="tab-list' not in html
    assert html.count('type="radio" class="tab-pick"') == 1
    assert "checked" in html


def test_every_case_is_named_by_its_own_radio_group() -> None:
    """Two blocks on one page share the document's radio namespace, so a name repeated across them
    would make choosing a case in one clear the other."""
    steps = [
        make_step(captures=[{"name": "token", "source": "body"}]),
        make_step(
            url="https://{{host}}/{{resource}}",
            headers={"Authorization": "Bearer {{token}}"},
            case_variable="resource",
            cases=[
                {"label": "widgets", "response": {"status": 200, "body": "[]"}},
                {"label": "gadgets", "response": {"status": 200, "body": "[]"}},
            ],
        ),
    ]
    html = render_html(parse_report(make_report(blocks=[make_flow(steps=steps)])))
    groups = re.findall(r'class="tab-pick" name="([^"]+)"', html)

    assert len(set(groups)) == 2
    assert len(groups) == 3


def test_two_blocks_on_one_page_never_share_a_radio_group() -> None:
    """The same hazard between whole blocks rather than between a flow's steps: a shared name would
    make choosing a case in one block clear the selection in the other."""

    def block(label: str) -> dict[str, object]:
        return {
            "type": "request",
            "label": label,
            "method": "GET",
            "url": "https://api.example.com/{{resource}}",
            "case_variable": "resource",
            "cases": _cases(2),
        }

    html = render_html(parse_report(make_report(blocks=[block("One"), block("Two")])))
    groups = re.findall(r'class="tab-pick" name="([^"]+)"', html)

    assert len(groups) == 4
    assert len(set(groups)) == 2


def test_a_flow_shows_its_steps_and_nothing_above_them() -> None:
    """A flow's steps carry the calls; a second rendering of the same two commands above them is the
    same content twice, and a reader working down the page meets it before the walkthrough."""
    html = render_html(parse_report(_tabbed_flow()))

    assert "rq-flowscript" not in html
    assert "Every step as one script" not in html
    assert "Copy the whole script" not in html
    assert html.count('class="rq-step"') == 2


def test_copying_leaves_out_every_hidden_node() -> None:
    """textContent walks hidden descendants, so a plain copy would carry the capture pipe the reader
    did not ask for. One rule covers it: hidden is not copied."""
    html = render_html(parse_report(_tabbed_flow()))
    script = _request_runtime_script(html)
    reader = script.split("function commandText", 1)[1].split("function copyCommand", 1)[0]

    assert 'querySelectorAll("[hidden]")' in reader
    assert "cloneNode(true)" in reader


def test_an_omitted_reason_phrase_falls_back_to_the_standard_text() -> None:
    report = _request_report(
        cases=[{"label": "one", "response": {"status": 404, "body": "{}"}}],
        case_variable=None,
        url="https://{{host}}/x",
    )

    html = render_html(parse_report(report))

    assert "404 Not Found" in html


def test_a_response_with_no_status_line_says_so_rather_than_rendering_a_blank_pill() -> None:
    report = _request_report(
        cases=[{"label": "one", "response": {"body": "a-bare-token"}}],
        case_variable=None,
        url="https://{{host}}/x",
    )

    html = render_html(parse_report(report))

    assert "no status line" in html


def test_a_declared_request_variable_is_not_an_unfilled_placeholder() -> None:
    assert find_placeholders(parse_report(_request_report())) == []


def test_a_mistyped_request_variable_is_still_caught_by_strict() -> None:
    report = _request_report(url="https://{{host}}/{{resource}}/{{tokne}}")

    assert find_placeholders(parse_report(report)) == ["tokne"]


def test_one_request_declaring_a_name_does_not_exempt_another_request_using_it() -> None:
    """The exemption is computed per block from that block's own declarations. A single shared set of
    declared names would let the first block's `host` silence the second block's undeclared one."""
    declares_host = {
        "type": "request",
        "label": "A",
        "method": "GET",
        "url": "https://{{host}}/a",
        "variables": [{"name": "host", "example": "api.example.com"}],
        "cases": [{"label": "one", "response": {"body": "{}"}}],
    }
    borrows_host = {
        "type": "request",
        "label": "B",
        "method": "GET",
        "url": "https://{{host}}/b",
        "cases": [{"label": "one", "response": {"body": "{}"}}],
    }

    report = parse_report(make_report(blocks=[declares_host, borrows_host]))

    assert find_placeholders(report) == ["host"]


def test_a_declared_request_variable_does_not_exempt_the_same_name_in_prose() -> None:
    request = _request_report()["blocks"]
    assert isinstance(request, list)
    report = make_report(blocks=[*request, {"type": "text", "body": "still {{host}} to fill"}])

    assert find_placeholders(parse_report(report)) == ["host"]


def test_the_runtime_script_ships_only_for_a_page_that_carries_a_request() -> None:
    assert "data-rq-slot" not in render_html(parse_report(make_report()))
    assert "data-rq-slot" in render_html(parse_report(_request_report()))


def test_every_inline_script_on_a_request_page_is_pinned_by_the_csp() -> None:
    """The script is included only for a page that carries a request, so the fixture the other CSP test
    renders never contains it. Without this, a stale pin would refuse the script in the browser and
    leave the suite green."""
    html = render_html(parse_report(_request_report()))
    csp = re.search(r'content="(default-src [^"]+)"', html)
    assert csp is not None
    script_src = csp.group(1).split("script-src ", 1)[1].split(";", 1)[0]

    scripts = inline_scripts(html)
    unpinned = [body[:40] for body in scripts if f"'sha256-{script_hash(body)}'" not in script_src]

    assert (any("data-rq-slot" in body for body in scripts), unpinned) == (True, [])


def test_a_declared_request_variable_is_not_a_location_of_a_blank_with_its_name() -> None:
    report = parse_report(
        make_report(
            blocks=[make_request(), {"type": "text", "body": "Call {{host}} first."}],
        )
    )

    assert (find_placeholders(report), placeholder_locations(report)) == (
        ["host"],
        {"host": ["blocks.1.body"]},
    )


def test_an_undeclared_request_variable_is_located_at_its_request_block() -> None:
    report = parse_report(make_report(blocks=[make_request(variables=[])]))

    assert placeholder_locations(report) == {"host": ["blocks.0.request"]}


def _command_page(**overrides: object) -> str:
    return render_html(parse_report(make_report(blocks=[make_command_request(**overrides)])))


def _pane_text(html: str, css_class: str) -> list[str]:
    """The reader-visible text of every `<pre class=css_class>`, tags stripped and entities decoded,
    hidden spans included, so a test sees exactly what the copy button reads before it prunes."""
    panes = re.findall(rf'<pre class="{css_class}">(.*?)</pre>', html, re.DOTALL)
    return [unescape(re.sub(r"<[^>]+>", "", pane)) for pane in panes]


def test_a_command_request_shows_the_command_verbatim_and_no_composed_request() -> None:
    html = _command_page()

    assert _pane_text(html, "rq-cmd") == [
        "{\nvault-run -- curl -s https://api.partner.example/v1/tiers | jq 'map({code, mapped})'"
        "\n} | tee /dev/tty | pbcopy"
    ]
    assert 'class="rq-wire"' not in html
    assert "curl -i -X" not in html


def test_a_multi_line_command_is_grouped_so_capture_takes_the_whole_output() -> None:
    html = _command_page(command="cd /srv/partner\nvault-run -- fetch-tiers\n")

    assert _pane_text(html, "rq-cmd") == [
        "{\ncd /srv/partner\nvault-run -- fetch-tiers\n} | tee /dev/tty | pbcopy"
    ]
    assert html.count('class="rq-pipe" hidden') == 2
    assert 'command.querySelectorAll(".rq-pipe")' in _request_runtime_script(html)


@pytest.mark.parametrize(
    ("command", "captured"),
    [
        pytest.param("echo first; echo second", "first\nsecond\n", id="sequence"),
        pytest.param("echo first # print it", "first\n", id="trailing-comment"),
        pytest.param("false || echo second", "second\n", id="or-list"),
        pytest.param("echo first && echo second", "first\nsecond\n", id="and-list"),
        pytest.param("echo first\necho second  # trailing comment\n", "first\nsecond\n", id="multi-line"),
    ],
)
def test_copy_and_capture_pipes_every_line_of_output_the_command_prints(
    tmp_path: Path, command: str, captured: str
) -> None:
    clipboard = tmp_path / "clipboard.txt"
    clipboard.write_text("", encoding="utf-8")
    [capture_text] = _pane_text(_command_page(command=command), "rq-cmd")
    runnable = capture_text.replace("tee /dev/tty", "tee /dev/null").replace("pbcopy", f"cat > '{clipboard}'")

    result = subprocess.run(["bash", "-c", runnable], capture_output=True, text=True, check=False)

    assert (result.returncode, result.stdout, result.stderr, clipboard.read_text(encoding="utf-8")) == (
        0,
        "",
        "",
        captured,
    )


def test_only_a_command_case_is_marked_so_the_live_pane_drops_its_status_chip() -> None:
    command_html = _command_page()
    composed_html = render_html(parse_report(_request_report()))

    assert '<section class="tab-pane" data-rq-case="0" data-rq-command>' in command_html
    assert 'host.closest("[data-rq-command]")' in _request_runtime_script(command_html)
    assert "data-rq-command>" not in composed_html


def test_a_reader_value_in_a_command_is_written_as_typed_with_no_shell_quoting() -> None:
    html = _command_page(
        command='vault-run -- curl -s "https://{{host}}/v1/tiers"',
        variables=[{"name": "host", "example": "api.partner.example"}],
    )

    assert '<span class="rq-slot" data-rq-slot="host" data-rq-quote="none">' in html


def test_each_case_of_a_command_request_shows_its_own_command() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "[]"}},
        {
            "label": "control",
            "tone": "success",
            "command": "vault-run -- fetch-regions",
            "response": {"body": "[]"},
        },
    ]
    html = _command_page(cases=cases)

    assert _pane_text(html, "rq-cmd") == [
        "{\nvault-run -- curl -s https://api.partner.example/v1/tiers | jq 'map({code, mapped})'"
        "\n} | tee /dev/tty | pbcopy",
        "{\nvault-run -- fetch-regions\n} | tee /dev/tty | pbcopy",
    ]


def test_a_case_tone_colours_its_tab_and_verdict_when_no_status_was_recorded() -> None:
    cases = [
        {"label": "finding", "tone": "warning", "response": {"body": "[]"}, "verdict": "No value mapped."},
        {"label": "control", "tone": "success", "response": {"body": "[1]"}, "verdict": "Mapped."},
    ]
    html = _command_page(cases=cases)

    assert re.findall(r'<span class="tab-dot (\w+)">', html) == ["warning", "success"]
    assert re.findall(r'<div class="rq-verdict (\w+)">', html) == ["warning", "success"]


def test_a_command_case_without_a_status_shows_output_and_no_status_chip() -> None:
    html = _command_page()

    assert "<span>Recorded output</span>" in html
    assert '<span class="rq-status' not in html
    assert "Recorded response" not in html


def test_a_composed_request_still_labels_a_missing_status() -> None:
    html = render_html(
        parse_report(_request_report(cases=[{"label": "widgets", "response": {"body": "abc"}}]))
    )

    assert "<span>Recorded response</span>" in html
    assert '<span class="rq-status neutral">no status line</span>' in html


def _query_page(**overrides: object) -> str:
    return render_html(parse_report(make_report(blocks=[make_query_request(**overrides)])))


def _empty_slot(name: str) -> str:
    return chr(0x2039) + name + chr(0x203A)


def _query_case(html: str) -> str:
    start = html.index('<section class="tab-pane"')
    return html[start : html.index("</section>", start) + len("</section>")]


def test_a_query_request_shows_the_query_highlighted_under_its_runner_with_a_copy_button() -> None:
    case = _query_case(_query_page())

    assert case == (
        '<section class="tab-pane" data-rq-case="0">\n'
        '<h4 class="tab-pane-hd">open orders</h4>\n'
        '<div class="rq-pane"><div class="rq-pane-hd"><span>Query</span>'
        '<span class="rq-runner">mongosh, orders database</span>'
        '<span class="rq-btns"><button type="button" class="rq-copy">Copy</button></span></div>'
        '<pre class="rq-cmd rq-query"><span class="t-pun">[{</span>'
        '&#34;$match&#34;<span class="t-pun">:</span> '
        '<span class="t-pun">{</span>&#34;status&#34;<span class="t-pun">:</span> '
        '<span class="t-str">&#34;open&#34;</span><span class="t-pun">}},</span> '
        '<span class="t-pun">{</span>&#34;$count&#34;<span class="t-pun">:</span> '
        '<span class="t-str">&#34;n&#34;</span><span class="t-pun">}]</span></pre></div>\n'
        '<div class="rq-pane"><div class="rq-pane-hd"><span>Recorded output</span></div>\n'
        '<pre class="rq-resp">[\n  {\n    &#34;n&#34;: 12\n  }\n]</pre></div>\n'
        "</section>"
    )


def test_a_query_request_has_no_run_affordance_capture_pane_or_composed_request() -> None:
    html = _query_page()

    assert [
        marker
        for marker in (
            "Run this",
            "Copy + capture",
            "rq-catch",
            "rq-paste",
            "rq-in",
            "rq-live",
            "rq-wire",
            "curl -i -X",
            "rq-pipe",
            "tee /dev/tty",
        )
        if marker in _query_case(html)
    ] == []


def test_the_copy_button_of_a_query_reads_the_query_text_with_its_slots_filled() -> None:
    query = {
        "runner": "psql",
        "lang": "sql",
        "content": "SELECT count(*) FROM orders WHERE status = '{{status}}'",
    }
    html = _query_page(
        query=query,
        variables=[{"name": "status", "example": "open"}],
        cases=[{"label": "open orders", "response": {"body": "12"}}],
    )

    assert _pane_text(html, "rq-cmd rq-query") == [
        f"SELECT count(*) FROM orders WHERE status = '{_empty_slot('status')}'"
    ]
    assert (
        '<span class="rq-slot" data-rq-slot="status" data-rq-quote="none">&lsaquo;status&rsaquo;</span>'
        in html
    )
    assert 'data-rq-var="status"' in html


def test_a_query_slot_inside_a_highlighted_string_stays_one_slot_with_no_shell_quoting() -> None:
    query = {"runner": "mongosh", "lang": "json", "content": '[{"$match": {"status": "{{status}}"}}]'}
    html = _query_page(query=query, variables=[{"name": "status"}])

    assert _pane_text(html, "rq-cmd rq-query") == [f'[{{"$match": {{"status": "{_empty_slot("status")}"}}}}]']
    assert html.count('data-rq-slot="status" data-rq-quote="none"') == 1


def test_each_case_of_a_query_request_with_a_case_axis_shows_its_own_value_written_in() -> None:
    query = {"runner": "mongosh", "lang": "json", "content": '[{"$match": {"status": "{{status}}"}}]'}
    cases = [
        {"label": "open", "tone": "warning", "response": {"body": '[{"n": 12}]'}},
        {"label": "closed", "tone": "success", "response": {"body": '[{"n": 3}]'}},
    ]
    html = _query_page(query=query, case_variable="status", cases=cases)

    assert _pane_text(html, "rq-cmd rq-query") == [
        '[{"$match": {"status": "open"}}]',
        '[{"$match": {"status": "closed"}}]',
    ]


def test_a_query_holding_both_stand_in_texts_is_shown_plain_with_its_slot_and_its_own_text() -> None:
    content = "SELECT '7000007', 'SKALDRSLOT0X', {{n}}"
    query = {"runner": "psql", "lang": "sql", "content": content}
    html = _query_page(query=query, variables=[{"name": "n"}])

    assert _pane_text(html, "rq-cmd rq-query") == [f"SELECT '7000007', 'SKALDRSLOT0X', {_empty_slot('n')}"]
    assert 'class="t-' not in _query_case(html)
    assert html.count('data-rq-slot="n" data-rq-quote="none"') == 1


def test_a_slot_in_a_number_position_renders_highlighted_and_still_a_slot() -> None:
    query = {"runner": "mongosh", "lang": "json", "content": '[{"$limit": {{n}}}]'}
    html = _query_page(query=query, variables=[{"name": "n"}])

    assert _pane_text(html, "rq-cmd rq-query") == [f'[{{"$limit": {_empty_slot("n")}}}]']
    assert 'class="t-pun"' in _query_case(html)
    assert html.count('data-rq-slot="n" data-rq-quote="none"') == 1


HOSTILE_RUNNER = "<script>alert(1)</script> & co"


ESCAPED_RUNNER_HEADER = (
    '<div class="rq-pane-hd"><span>Query</span>'
    '<span class="rq-runner">&lt;script&gt;alert(1)&lt;/script&gt; &amp; co</span>'
)


def test_a_hostile_runner_and_query_are_escaped_on_the_highlighted_path() -> None:
    query = {"runner": HOSTILE_RUNNER, "lang": "json", "content": '["<script>&"]'}
    case = _query_case(_query_page(query=query))

    assert ESCAPED_RUNNER_HEADER in case
    assert (
        '<pre class="rq-cmd rq-query"><span class="t-pun">[</span>'
        '<span class="t-str">&#34;&lt;script&gt;&amp;&#34;</span><span class="t-pun">]</span></pre>'
    ) in case
    assert "<script>" not in case


def test_a_hostile_runner_and_query_are_escaped_on_the_plain_path() -> None:
    content = "<b>x</b> & 7000007 SKALDRSLOT0X {{n}}"
    query = {"runner": HOSTILE_RUNNER, "lang": "json", "content": content}
    case = _query_case(_query_page(query=query, variables=[{"name": "n"}]))

    assert ESCAPED_RUNNER_HEADER in case
    assert (
        '<pre class="rq-cmd rq-query">&lt;b&gt;x&lt;/b&gt; &amp; 7000007 SKALDRSLOT0X '
        '<span class="rq-slot" data-rq-slot="n" data-rq-quote="none">&lsaquo;n&rsaquo;</span></pre>'
    ) in case
    assert "<b>" not in case


def test_a_request_flow_step_can_record_a_query_with_no_paste_pane() -> None:
    step: dict[str, Any] = {
        "label": "Count open orders",
        "query": {"runner": "psql", "lang": "sql", "content": "SELECT count(*) FROM orders"},
        "cases": [{"label": "open", "response": {"body": "12"}}],
    }
    later_query = {"runner": "psql", "lang": "sql", "content": "SELECT 0"}
    later = {**step, "label": "Count closed orders", "query": later_query}
    html = render_html(parse_report(make_report(blocks=[make_flow(variables=[], steps=[step, later])])))

    assert _pane_text(html, "rq-cmd rq-query") == ["SELECT count(*) FROM orders", "SELECT 0"]
    assert "rq-paste" not in html.split('<section class="rq-step">', 1)[1]
    assert "Copy + capture" not in html


def test_a_slot_standing_where_a_name_would_in_a_query_stays_a_slot() -> None:
    query = {"runner": "psql", "lang": "sql", "content": "SELECT {{column}}"}
    html = _query_page(query=query, variables=[{"name": "column"}])

    assert _pane_text(html, "rq-cmd rq-query") == [f"SELECT {_empty_slot('column')}"]


def test_a_query_case_reads_recorded_output_and_a_tone_the_way_a_command_case_does() -> None:
    cases = [{"label": "open", "tone": "warning", "response": {"body": '[{"n": 12}]'}, "verdict": "Twelve."}]
    html = _query_page(cases=cases)

    assert "<span>Recorded output</span>" in html
    assert '<span class="rq-status' not in html
    assert re.findall(r'<div class="rq-verdict (\w+)">', html) == ["warning"]


def test_a_command_note_renders_under_the_command_as_rich_text() -> None:
    html = _command_page(command_note="The API omits `mapped` when empty, so `jq` names it to force a null.")

    assert '<p class="rq-cnote">The API omits <code>mapped</code> when empty' in html


@pytest.mark.parametrize(
    ("body", "shown"),
    [
        pytest.param(
            '[{"code": "STANDARD", "mapped": null}]',
            '[\n  {\n    "code": "STANDARD",\n    "mapped": null\n  }\n]',
            id="json-array",
        ),
        pytest.param('{"total":0}', '{\n  "total": 0\n}', id="json-object"),
        pytest.param("eyJhbGciOi.token", "eyJhbGciOi.token", id="bare-token"),
        pytest.param("42", "42", id="json-scalar-left-alone"),
        pytest.param(
            '[\n  {"code": "STANDARD", "mapped": null},\n  {"code": "PREMIUM", "mapped": null}\n]',
            '[\n  {"code": "STANDARD", "mapped": null},\n  {"code": "PREMIUM", "mapped": null}\n]',
            id="author-laid-out-json-kept",
        ),
    ],
)
def test_a_recorded_one_line_json_body_is_pretty_printed_and_anything_else_is_verbatim(
    body: str, shown: str
) -> None:
    html = _command_page(cases=[{"label": "one", "response": {"body": body}}])

    assert _pane_text(html, "rq-resp") == [shown]
