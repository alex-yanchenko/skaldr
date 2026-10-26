import pytest

from skaldr.models import parse_report
from skaldr.render import render_html
from tests.factories import make_report


def test_swimlane_columns_are_fluid_so_a_few_columns_fill_the_width() -> None:
    """Data columns are a minmax(150px, 1fr) track: they share the width evenly with a 150px floor, so
    a few columns fill the page instead of huddling at a fixed 150px."""
    html = render_html(
        parse_report(
            make_report(
                blocks=[
                    {
                        "type": "swimlane",
                        "lanes": ["A"],
                        "columns": ["C1"],
                        "steps": [{"lane": "A", "col": "C1", "n": "1", "label": "x"}],
                    }
                ]
            )
        )
    )

    assert "--swim-col:minmax(150px, 1fr)" in html


def test_swimlane_plain_renders_gutter_labels_and_stacked_tickets() -> None:
    """A groupless swimlane: header + lane rows only (no poke zones), gutter labels, and two steps in
    the same lane/column stacked in one cell with their free-string `n` verbatim. No group caps."""
    block = {
        "type": "swimlane",
        "lanes": ["Eng"],
        "columns": ["S1"],
        "steps": [
            {"lane": "Eng", "col": "S1", "n": "3a", "label": "A"},
            {"lane": "Eng", "col": "S1", "n": "3b", "label": "B"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert "grid-template-columns:max-content repeat(1, var(--swim-col))" in html
    assert "grid-template-rows:auto auto" in html  # header + one lane, no poke zones
    assert 'class="swim-gut"' in html and ">Eng</div>" in html
    assert 'class="swim-hlabel"' in html and ">S1</div>" in html
    # both tickets stacked in a single cell, in order (no `state` → the default `todo` class)
    assert (
        '<div class="swim-tkt todo"><span class="swim-n">3a</span>'
        '<span class="swim-body"><span class="swim-l">A</span></span></div>'
        '<div class="swim-tkt todo"><span class="swim-n">3b</span>'
        '<span class="swim-body"><span class="swim-l">B</span></span></div>' in html
    )
    assert 'class="swim-cap' not in html  # no groups → no caps
    assert 'class="swim-vdash"' not in html  # no group splits → no dashed lines


def test_swimlane_grouped_renders_coloured_caps_tints_and_dashed_splits() -> None:
    """MVP spans S1-S2, Beta and GA split S2, GA continues to S3. Caps carry the group's palette class
    and label, cells and header cells carry the group tint, S2's internal splits render as dashes, and
    the split sprint's label is written exactly once."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["S1", "S2", "S3"],
        "groups": [
            {"name": "MVP", "color": "blue", "columns": ["S1", "S2"]},
            {"name": "Beta", "color": "amber", "columns": ["S2"]},
            {"name": "GA", "color": "violet", "columns": ["S2", "S3"]},
        ],
        "steps": [
            {"lane": "R", "col": "S1", "n": "1", "label": "a"},
            {"lane": "R", "col": "S2", "group": "Beta", "n": "2", "label": "b"},
            {"lane": "R", "col": "S3", "n": "3", "label": "c"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert "grid-template-rows:var(--swim-poke) auto auto var(--swim-pokeb)" in html
    # top caps carry the palette colour class + a dot + the group label; the outermost caps also carry
    # a grey outer edge (MVP leftmost → left, GA rightmost → right) that rounds with the accent corner
    assert 'class="swim-cap blue left"' in html and '<span class="swim-dot"></span>MVP</div>' in html
    assert 'class="swim-cap amber"' in html and '<span class="swim-dot"></span>Beta</div>' in html
    assert 'class="swim-cap violet right"' in html and '<span class="swim-dot"></span>GA</div>' in html
    assert 'class="swim-capb blue left"' in html  # matching bottom cap, same edge
    # the rounded outer frame is drawn on top of the tints
    # GA owns the rightmost column, so the frame squares its right corners to meet GA's right border
    assert 'class="swim-frame sq-right"' in html
    # cells and header cells carry the group tint class
    assert 'class="swim-cell blue"' in html and 'class="swim-cell amber"' in html
    assert 'class="swim-hcell blue"' in html
    # the two S2-internal group splits render as dashed overlays
    assert html.count('class="swim-vdash"') == 2
    # the split sprint's label is written exactly once, spanning its sub-columns
    assert html.count(">S2</div>") == 1
    # the Beta step landed in its resolved sub-column
    assert '<span class="swim-n">2</span><span class="swim-body"><span class="swim-l">b</span></span>' in html


def test_swimlane_adjacent_caps_render_a_poke_solid_but_an_ungrouped_boundary_does_not() -> None:
    """Two groups each owning a whole column render a full-height `poke` solid at the boundary between
    them; a boundary where one side is ungrouped renders a plain (non-poke) solid instead."""
    two_caps = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["S1", "S2"],
        "groups": [
            {"name": "A", "color": "blue", "columns": ["S1"]},
            {"name": "B", "color": "amber", "columns": ["S2"]},
        ],
        "steps": [
            {"lane": "R", "col": "S1", "n": "1", "label": "a"},
            {"lane": "R", "col": "S2", "n": "2", "label": "b"},
        ],
    }
    grouped_then_ungrouped = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["S1", "S2"],
        "groups": [{"name": "A", "color": "blue", "columns": ["S1"]}],
        "steps": [
            {"lane": "R", "col": "S1", "n": "1", "label": "a"},
            {"lane": "R", "col": "S2", "n": "2", "label": "b"},
        ],
    }

    two_caps_html = render_html(parse_report(make_report(blocks=[two_caps])))
    ungrouped_html = render_html(parse_report(make_report(blocks=[grouped_then_ungrouped])))

    assert 'class="swim-vsolid poke"' in two_caps_html
    assert "poke" not in ungrouped_html.split('class="swim-vsolid', 1)[1].split(">", 1)[0]
    assert 'class="swim-vsolid poke"' not in ungrouped_html


def test_swimlane_group_spanning_all_columns_renders_both_edge_classes() -> None:
    """A group covering every column is leftmost AND rightmost, so its cap carries both edge classes."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2"],
        "groups": [{"name": "All", "color": "green", "columns": ["C1", "C2"]}],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "a"},
            {"lane": "R", "col": "C2", "n": "2", "label": "b"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert 'class="swim-cap green left right"' in html
    assert 'class="swim-capb green left right"' in html


def test_swimlane_values_render_a_footer_row_and_lane_and_group_totals() -> None:
    """`value` on steps renders a footer totals row (label + per-column sums), a lane total beside the
    gutter label, and a group total on the cap."""
    block = {
        "type": "swimlane",
        "lanes": ["Brent"],
        "columns": ["S1", "S2"],
        "groups": [{"name": "MVP", "color": "blue", "columns": ["S1", "S2"]}],
        "steps": [
            {"lane": "Brent", "col": "S1", "n": "1", "label": "a", "value": 3},
            {"lane": "Brent", "col": "S2", "n": "2", "label": "b", "value": 5},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # footer row: the "Total" gutter label and each column's sum, each as a swim-tot pill in a cell
    assert '<div class="swim-gut swim-foot-lbl"' in html
    assert html.count('class="swim-foot"') == 2
    assert '<span class="swim-tot">3</span>' in html and '<span class="swim-tot">5</span>' in html
    # lane total (3+5) beside the gutter label AND the MVP cap's group total → two more totals of 8
    assert html.count('<span class="swim-tot">8</span>') == 2


def test_swimlane_without_values_renders_no_footer_or_totals() -> None:
    """No `value` anywhere → no footer row and no inline totals."""
    block = {
        "type": "swimlane",
        "lanes": ["Brent"],
        "columns": ["S1"],
        "groups": [{"name": "MVP", "color": "blue", "columns": ["S1"]}],
        "steps": [{"lane": "Brent", "col": "S1", "n": "1", "label": "a"}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # the .swim-foot/.swim-tot CSS rules are always inlined; assert no rendered ELEMENT carries them
    assert 'class="swim-foot"' not in html
    assert 'class="swim-gut swim-foot-lbl"' not in html
    assert 'class="swim-tot"' not in html


def test_swimlane_step_value_renders_on_the_ticket() -> None:
    """A step's own `value` renders as a trailing compartment on its ticket; a step without one omits it."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2"],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "sized", "value": 5},
            {"lane": "R", "col": "C2", "n": "2", "label": "unsized"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # the sized ticket carries its value compartment; exactly one ticket has one
    assert (
        '<span class="swim-body"><span class="swim-l">sized</span></span><span class="swim-tkt-v">5</span>'
        in html
    )
    assert '<span class="swim-l">unsized</span></span></div>' in html
    assert html.count('class="swim-tkt-v"') == 1


def test_swimlane_step_url_links_the_number_and_state_styles_the_ticket() -> None:
    """A step `url` renders the number as a link; `state` always adds its progress class; the two
    compose on one step. A step with no `state` defaults to `todo` — the class is always present."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2", "C3", "C4", "C5"],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "linked", "url": "https://example.com/PROJ-1"},
            {"lane": "R", "col": "C2", "n": "2", "label": "wip", "state": "current"},
            {"lane": "R", "col": "C3", "n": "3", "label": "parked", "state": "deferred"},
            {
                "lane": "R",
                "col": "C4",
                "n": "4",
                "label": "both",
                "url": "https://example.com/PROJ-4",
                "state": "blocked",
            },
            {"lane": "R", "col": "C5", "n": "5", "label": "shipped", "state": "done"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    # url → linked number; a step with no `state` defaults to `todo`, and the class is always emitted
    assert '<div class="swim-tkt todo"><a class="swim-n" href="https://example.com/PROJ-1">1</a>' in html
    assert '<div class="swim-tkt current"><span class="swim-n">2</span>' in html  # no url → plain span
    assert '<div class="swim-tkt deferred">' in html
    assert '<div class="swim-tkt done"><span class="swim-n">5</span>' in html
    # url + blocked compose: a blocked ticket whose number is a link
    assert '<div class="swim-tkt blocked"><a class="swim-n" href="https://example.com/PROJ-4">4</a>' in html
    # no step ever renders without a state class
    assert '<div class="swim-tkt">' not in html


def test_an_unset_swimlane_step_is_drawn_and_listed_as_todo_in_the_html() -> None:
    swimlane = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2"],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "a"},
            {"lane": "R", "col": "C2", "n": "2", "label": "b", "state": "done"},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[swimlane])))

    assert '<div class="swim-tkt todo">' in html
    assert (
        '<div class="swim-legend">'
        '<span class="swim-leg"><span class="swim-leg-sw done"></span>done</span>'
        '<span class="swim-leg"><span class="swim-leg-sw todo"></span>todo</span>'
        "</div>" in html
    )


def test_swimlane_state_legend_renders_used_states_and_is_suppressed_when_single_state() -> None:
    """A swimlane with ≥2 states renders an auto legend of swatch+name for each used state (canonical
    order, used-only); a single-state grid renders no legend at all."""
    multi = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2", "C3"],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "a", "state": "blocked"},
            {"lane": "R", "col": "C2", "n": "2", "label": "b", "state": "done"},
            {"lane": "R", "col": "C3", "n": "3", "label": "c", "state": "current"},
        ],
    }
    html = render_html(parse_report(make_report(blocks=[multi])))

    assert (
        '<div class="swim-legend">'
        '<span class="swim-leg"><span class="swim-leg-sw done"></span>done</span>'
        '<span class="swim-leg"><span class="swim-leg-sw current"></span>current</span>'
        '<span class="swim-leg"><span class="swim-leg-sw blocked"></span>blocked</span>'
        "</div>" in html
    )
    assert "swim-leg-sw todo" not in html  # todo unused → not listed
    assert "swim-leg-sw deferred" not in html

    single = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2"],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "a"},
            {"lane": "R", "col": "C2", "n": "2", "label": "b"},
        ],
    }
    assert 'class="swim-legend"' not in render_html(parse_report(make_report(blocks=[single])))


def test_swimlane_sets_n_width_css_var_so_number_badges_align() -> None:
    """The widest step number drives a --swim-n-ch var on the grid; every badge sizes to it (mono font)
    so the labels line up in a column instead of starting at ragged x."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2"],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "a"},
            {"lane": "R", "col": "C2", "n": "113", "label": "b"},
        ],
    }
    html = render_html(parse_report(make_report(blocks=[block])))

    assert "--swim-n-ch:3" in html


def test_swimlane_column_sub_renders_and_ids_decouple_reference_from_display() -> None:
    """A column `sub` renders as a caption under the header; with ids, steps reference the id while the
    header shows the display name and the gutter shows the lane's display name."""
    block = {
        "type": "swimlane",
        "lanes": [{"id": "eng", "name": "Engineering"}],
        "columns": [{"id": "s1", "name": "Sprint 1", "sub": "→ MVP demo"}],
        "steps": [{"lane": "eng", "col": "s1", "n": "1", "label": "Build"}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span class="swim-hsub">→ MVP demo</span>' in html  # caption under the header
    assert ">Sprint 1<span" in html  # header shows the display name, not the id "s1"
    assert ">Engineering</div>" in html  # gutter shows the lane's display name, not "eng"


def test_swimlane_depends_on_renders_a_needs_marker_of_the_dependency_numbers() -> None:
    """`depends_on` renders a marker of the referenced steps' numbers, comma-joined; a step with none
    gets no marker. The "needs " prefix is CSS, so the element text is just the numbers."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1", "C2", "C3"],
        "steps": [
            {"lane": "R", "col": "C1", "n": "1", "label": "a", "id": "first"},
            {"lane": "R", "col": "C2", "n": "2", "label": "b", "id": "second", "depends_on": ["first"]},
            {"lane": "R", "col": "C3", "n": "3", "label": "c", "depends_on": ["first", "second"]},
        ],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert '<span class="swim-dep">1</span>' in html  # step 2 needs step 1
    assert '<span class="swim-dep">1, 2</span>' in html  # step 3 needs steps 1 and 2
    assert html.count('class="swim-dep"') == 2  # step 1 has no dependency → no marker


@pytest.mark.parametrize(
    "url", ["https://example.com/PROJ-1", "http://example.com/PROJ-1", "mailto:pm@example.com"]
)
def test_swimlane_step_url_accepts_each_safe_scheme(url: str) -> None:
    """All three allowed schemes render the number as a link out to the given url."""
    block = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["C1"],
        "steps": [{"lane": "R", "col": "C1", "n": "1", "label": "a", "url": url}],
    }

    html = render_html(parse_report(make_report(blocks=[block])))

    assert f'<a class="swim-n" href="{url}">1</a>' in html


def test_swimlane_split_column_footer_is_bare_but_normal_footer_is_banded() -> None:
    """A column split across groups renders a bare (bandless) totals row; an unsplit one keeps the band."""
    split = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["S1", "S2"],
        "groups": [
            {"name": "A", "color": "blue", "columns": ["S1", "S2"]},
            {"name": "B", "color": "amber", "columns": ["S2"]},
        ],
        "steps": [
            {"lane": "R", "col": "S1", "n": "1", "label": "a", "value": 2},
            {"lane": "R", "col": "S2", "group": "A", "n": "2", "label": "b", "value": 3},
            {"lane": "R", "col": "S2", "group": "B", "n": "3", "label": "c", "value": 4},
        ],
    }
    unsplit = {
        "type": "swimlane",
        "lanes": ["R"],
        "columns": ["S1", "S2"],
        "groups": [{"name": "A", "color": "blue", "columns": ["S1", "S2"]}],
        "steps": [
            {"lane": "R", "col": "S1", "n": "1", "label": "a", "value": 2},
            {"lane": "R", "col": "S2", "n": "2", "label": "b", "value": 3},
        ],
    }

    split_html = render_html(parse_report(make_report(blocks=[split])))
    unsplit_html = render_html(parse_report(make_report(blocks=[unsplit])))

    assert 'class="swim-foot bare"' in split_html
    assert 'class="swim-gut swim-foot-lbl bare"' in split_html
    assert 'class="swim-foot bare"' not in unsplit_html
    assert 'class="swim-foot"' in unsplit_html
