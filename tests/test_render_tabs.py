import re
from collections import Counter

import pytest

from skaldr import compute
from skaldr.models import package_path, parse_report
from skaldr.render import render_embed, render_html
from tests.factories import (
    make_cell,
    make_command_request,
    make_flow,
    make_grid,
    make_report,
    make_tab,
    make_tabs,
    make_toggle,
)
from tests.factories.render_factory import container_rules, inline_scripts, script_hash, strip_rail_rules


def test_choosing_a_tab_is_a_radio_each_label_selects_with_no_handler_on_the_markup() -> None:
    html = render_html(parse_report(make_report(blocks=[make_tabs()])))

    assert (
        re.findall(r'<input type="radio" class="tab-pick" name="([^"]+)" id="([^"]+)"', html),
        re.findall(r'<label for="([^"]+)"', html),
        re.findall(r"\son[a-z]+=", html),
    ) == ([("tb0", "tb0_0"), ("tb0", "tb0_1")], ["tb0_0", "tb0_1"], [])


def test_a_tabs_block_strip_becomes_a_rail_below_the_width_its_labels_need() -> None:
    html = render_html(parse_report(make_report(blocks=[make_tabs()])))

    assert container_rules(html) == [(compute.strip_width(["Floor", "System"]), strip_rail_rules("tb0"))]


def test_a_tab_tone_outside_the_case_tones_still_gets_a_coloured_dot() -> None:
    block = make_tabs(make_tab("Floor", tone="accent"), make_tab("System", tone="accent"))
    html = render_html(parse_report(make_report(blocks=[block])))
    css = package_path("styles.css").read_text(encoding="utf-8")

    assert '<label for="tb0_0"><span class="tab-dot accent"></span>Floor</label>' in html
    assert ".tab-dot.accent{background:var(--accent-fg)}" in css


def test_print_shows_every_tab_under_its_label_and_drops_the_strip() -> None:
    css = package_path("styles.css").read_text(encoding="utf-8")
    print_rules = re.sub(r"\s+", " ", css[css.index("@layer print {") :])
    expected = [
        ".tabs .tab-pane{display:block}",
        ":is(.rq,.tabs) .tab-pane-hd{display:block; padding-top:var(--s2); border-top:1px solid var(--rule); "
        "break-after:avoid}",
        ":is(.rq,.tabs) .tab-list,.rq .rq-copy,.rq .rq-clear,.rq .rq-paste{display:none}",
    ]

    assert [rule for rule in expected if rule not in print_rules] == []


def test_a_heading_inside_a_tab_is_a_link_target() -> None:
    block = {
        "type": "tabs",
        "tabs": [
            {
                "label": "Floor",
                "blocks": [{"type": "heading", "level": 4, "text": "Aisle C", "id": "aisle-c"}],
            },
            {"label": "System", "blocks": [{"type": "text", "body": "See [aisle C](#aisle-c)."}]},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<h4 id="aisle-c">Aisle C</h4>\n</section>' in html
    assert '<p class="text">See <a href="#aisle-c">aisle C</a>.</p></section>' in html


def test_an_outer_tab_strip_rail_rule_never_reaches_a_strip_nested_in_one_of_its_tabs() -> None:
    inner = make_tabs(make_tab("Inner"), make_tab("Other"))
    outer = make_tabs(make_tab("Outer", inner), make_tab("Second"))

    html = render_html(parse_report(make_report(blocks=[outer])))

    assert container_rules(html) == [
        (compute.strip_width(["Outer", "Second"]), strip_rail_rules("tb0")),
        (compute.strip_width(["Inner", "Other"]), strip_rail_rules("tb1")),
    ]


def test_a_heading_slugged_like_a_radio_id_leaves_every_label_bound_to_its_radio() -> None:
    cases = [{"label": "a", "response": {"body": "x"}}, {"label": "b", "response": {"body": "y"}}]
    blocks = [
        {"type": "heading", "text": "tb0 0"},
        {"type": "heading", "text": "rq0 0"},
        make_tabs(),
        make_command_request(cases=cases),
    ]

    html = render_html(parse_report(make_report(blocks=blocks)))
    repeated_ids = [name for name, count in Counter(re.findall(r' id="([^"]+)"', html)).items() if count > 1]
    radio_ids = re.findall(r'<input type="radio" class="tab-pick" name="[^"]+" id="([^"]+)"', html)
    label_targets = re.findall(r'<label for="([^"]+)"', html)

    assert (repeated_ids, label_targets) == ([], radio_ids)


CURRENT_HASH_CLICK_LISTENER = (
    '\tdocument.addEventListener("click", function (event) {\n'
    "\t\tvar link = event.target instanceof Element ? event.target.closest('a[href^=\"#\"]') : null;\n"
    "\t\tif (link && link.hash === location.hash) revealHashTarget();\n"
    "\t});\n"
)


STRIP_ANCHOR_SCRIPT = (
    "<script>\n"
    "(function () {\n"
    "\tfunction picksAround(target) {\n"
    "\t\tvar picks = [];\n"
    '\t\tfor (var pane = target.closest(".tab-pane"); '
    'pane; pane = pane.parentElement.closest(".tab-pane")) {\n'
    "\t\t\tvar pick = pane.previousElementSibling;\n"
    '\t\t\tif (pick && pick.classList.contains("tab-pick")) picks.unshift(pick);\n'
    "\t\t}\n"
    "\t\treturn picks;\n"
    "\t}\n"
    "\tfunction revealHashTarget() {\n"
    "\t\tvar id;\n"
    "\t\ttry {\n"
    "\t\t\tid = decodeURIComponent(location.hash.slice(1));\n"
    "\t\t} catch (error) {\n"
    "\t\t\treturn;\n"
    "\t\t}\n"
    "\t\tvar target = id && document.getElementById(id);\n"
    "\t\tif (!target) return;\n"
    "\t\tvar picks = picksAround(target);\n"
    "\t\tif (!picks.length) return;\n"
    "\t\tpicks.forEach(function (pick) {\n"
    "\t\t\tpick.checked = true;\n"
    '\t\t\tpick.dispatchEvent(new Event("change", { bubbles: true }));\n'
    "\t\t});\n"
    "\t\ttarget.scrollIntoView();\n"
    "\t}\n"
    '\twindow.addEventListener("hashchange", revealHashTarget);\n'
    f"{CURRENT_HASH_CLICK_LISTENER}"
    "\trevealHashTarget();\n"
    "})();\n"
    "</script>"
)


def test_a_click_on_a_link_to_the_hash_already_current_reveals_its_target_again() -> None:
    html = render_html(parse_report(make_report(blocks=[make_tabs()])))

    assert html.count(CURRENT_HASH_CLICK_LISTENER) == 1


@pytest.mark.parametrize(
    "blocks",
    [
        pytest.param([make_tabs()], id="tabs"),
        pytest.param([make_command_request()], id="request"),
        pytest.param([make_flow()], id="request-flow"),
    ],
)
def test_a_page_with_a_tab_strip_carries_the_script_that_opens_the_tab_holding_a_linked_target(
    blocks: list[dict[str, object]],
) -> None:
    report = parse_report(make_report(blocks=blocks))

    assert [html.count(STRIP_ANCHOR_SCRIPT) for html in (render_html(report), render_embed(report))] == [1, 1]


def test_a_page_without_a_tab_strip_carries_no_script_to_open_one() -> None:
    report = parse_report(make_report(blocks=[make_toggle(), {"type": "heading", "text": "Plain"}]))

    assert [STRIP_ANCHOR_SCRIPT in html for html in (render_html(report), render_embed(report))] == [
        False,
        False,
    ]


@pytest.mark.parametrize(
    "container",
    [
        pytest.param({"type": "section", "title": "S", "blocks": [make_tabs()]}, id="section"),
        pytest.param({"type": "panel", "title": "P", "blocks": [make_tabs()]}, id="panel"),
        pytest.param(make_toggle(make_tabs()), id="toggle"),
        pytest.param(make_grid([make_cell(6, [make_toggle(make_tabs())])]), id="inner-toggle"),
        pytest.param(make_grid([make_cell(6, [make_tabs()])]), id="grid-cell"),
        pytest.param(
            make_grid([make_cell(6, [make_grid([make_cell(6, [make_tabs()])])])]), id="inner-grid-cell"
        ),
        pytest.param(
            {"type": "walkthrough", "steps": [{"label": "Go", "detail": [make_tabs()]}]},
            id="walkthrough-detail",
        ),
    ],
)
def test_a_tabs_block_inside_any_container_renders_its_radios_and_rail(container: dict[str, object]) -> None:
    html = render_html(parse_report(make_report(blocks=[container])))

    assert (
        re.findall(r'class="tab-pick" name="([^"]+)" id="([^"]+)"', html),
        container_rules(html),
    ) == (
        [("tb0", "tb0_0"), ("tb0", "tb0_1")],
        [(compute.strip_width(["Floor", "System"]), strip_rail_rules("tb0"))],
    )


def test_every_inline_script_on_a_page_with_a_tab_strip_is_pinned_by_the_csp() -> None:
    block = make_tabs(make_tab("One"), make_tab("Two"))
    html = render_html(parse_report(make_report(blocks=[block])))
    csp = re.search(r'content="(default-src [^"]+)"', html)
    assert csp is not None
    script_src = csp.group(1).split("script-src ", 1)[1].split(";", 1)[0]

    scripts = inline_scripts(html)
    unpinned = [body[:40] for body in scripts if f"'sha256-{script_hash(body)}'" not in script_src]

    assert (any('closest(".tab-pane")' in body for body in scripts), unpinned) == (True, [])
