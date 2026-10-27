import re

from skaldr.models import package_path

TINT_PAIR = re.compile(
    r"light-dark\(color-mix\(in srgb, (?P<colour>[^%]+?) (?P<light>[\d.]+)%, transparent\), "
    r"color-mix\(in srgb, (?P=colour) (?P<dark>[\d.]+)%, transparent\)\)"
)
MOTION_QUERY = "@media screen and (prefers-reduced-motion: no-preference){"
SIMPLE_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
TIME_VALUE = re.compile(r"(?<![\w.-])\d*\.?\d+m?s\b")


def stylesheet() -> str:
    return package_path("styles.css").read_text(encoding="utf-8")


def block_opened_by(css: str, opener: str) -> str:
    start = css.index(opener) + len(opener)
    depth = 1
    cursor = start
    while depth:
        depth += {"{": 1, "}": -1}.get(css[cursor], 0)
        cursor += 1
    return css[start : cursor - 1]


def motion_block() -> str:
    return block_opened_by(stylesheet(), MOTION_QUERY)


def stylesheet_without_motion() -> str:
    return stylesheet().replace(MOTION_QUERY + motion_block() + "}", "")


def rules_declaring(css: str, property_name: str) -> list[tuple[str, str]]:
    return [
        (selector.strip(), body)
        for selector, body in SIMPLE_RULE.findall(css)
        if re.search(rf"(?<![\w-]){property_name}:", body)
    ]


def test_the_glow_in_dark_is_weaker_than_in_light() -> None:
    pairs = [
        (pair["colour"], float(pair["light"]), float(pair["dark"]))
        for pair in TINT_PAIR.finditer(stylesheet())
        if pair["colour"] != "var(--ink)"
    ]

    assert (pairs != [], [pair for pair in pairs if pair[2] >= pair[1]]) == (True, [])


def test_all_motion_sits_in_one_screen_only_block_for_readers_who_allow_it() -> None:
    assert stylesheet().count(MOTION_QUERY) == 1


def test_nothing_animates_outside_that_block() -> None:
    outside = stylesheet_without_motion()

    assert [word for word in ("@keyframes", "animation", "transition") if word in outside] == []


def test_every_animation_follows_the_scroll_except_the_ones_started_by_hovering() -> None:
    off_the_scroll = [
        selector
        for selector, body in rules_declaring(motion_block(), "animation")
        if "animation-timeline" not in body and ":hover" not in selector
    ]

    assert off_the_scroll == []


def test_scroll_timelines_are_only_used_where_the_browser_supports_them() -> None:
    motion = motion_block()
    opener = "@supports (animation-timeline: view()){"
    guarded = block_opened_by(motion, opener)

    assert (
        "animation-timeline" in guarded,
        "animation-timeline" in motion.replace(opener + guarded, ""),
    ) == (
        True,
        False,
    )


def test_no_animation_waits_before_it_starts() -> None:
    delayed = [
        selector
        for selector, body in rules_declaring(stylesheet(), "animation")
        if len(TIME_VALUE.findall(re.findall(r"(?<![\w-])animation:([^;}]*)", body)[0])) > 1
    ]

    assert ("animation-delay" in stylesheet(), delayed) == (False, [])


def test_no_easing_overshoots() -> None:
    curves = re.findall(r"cubic-bezier\(([^)]*)\)", stylesheet())
    overshooting = [
        curve for curve in curves if not all(0.0 <= float(value) <= 1.0 for value in curve.split(",")[1::2])
    ]

    assert (curves != [], overshooting) == (True, [])


def test_the_entrance_range_is_a_fixed_length_so_a_tall_block_is_not_left_faded() -> None:
    ranges = re.findall(r"animation-range:([^;}]*)", motion_block())
    in_percent_from_the_entry = [
        value for value in ranges if re.search(r"entry\s+\d+%\s+entry\s+\d+%", value)
    ]

    assert (ranges != [], in_percent_from_the_entry) == (True, [])


def test_the_border_light_of_a_card_runs_only_where_the_pointer_can_hover() -> None:
    motion = motion_block()
    guarded = block_opened_by(motion, "@media (hover:hover){")
    spinning_outside = [
        selector
        for selector, body in rules_declaring(motion.replace(guarded, ""), "animation")
        if "skaldr-spin" in body
    ]

    assert (rules_declaring(guarded, "animation") != [], spinning_outside) == (True, [])


def test_chart_shapes_share_one_named_timeline() -> None:
    motion = motion_block()
    declared = re.findall(r"view-timeline:\s*(--[\w-]+)", stylesheet())
    used = set(re.findall(r"animation-timeline:\s*(--[\w-]+)", motion))

    assert (len(declared), used <= set(declared), used != set()) == (1, True, True)


def test_the_contents_panel_lights_the_section_in_view_by_scroll_tracking() -> None:
    css = stylesheet()

    assert ("scroll-target-group:auto" in css, ".toc-pop a:target-current{" in css) == (True, True)


def test_the_contents_button_and_panel_stay_hidden_in_a_browser_without_popovers() -> None:
    css = stylesheet()
    shown_only_with_support = block_opened_by(css, "@supports selector(:popover-open){")

    assert (
        ".toc-btn{display:none}" in css,
        ".toc-pop{display:none}" in css,
        ".toc-btn{display:flex}" in shown_only_with_support,
        ".toc-pop:popover-open{display:block}" in shown_only_with_support,
    ) == (True, True, True, True)


def test_the_corner_row_holding_both_buttons_and_the_panel_is_hidden_on_paper() -> None:
    printed = stylesheet().split("@layer print {", 1)[1]

    assert ".sc,.skaldr-live{display:none}" in printed


def test_gradient_clipped_text_falls_back_to_the_system_text_colour_in_forced_colours() -> None:
    forced = block_opened_by(stylesheet(), "@media (forced-colors: active){")

    assert (".hero h1" in forced, ".wrap.numbered > h2::before" in forced, "color:CanvasText" in forced) == (
        True,
        True,
        True,
    )


def test_a_section_marker_is_the_same_glyph_open_and_closed() -> None:
    css = stylesheet()

    assert (css.count('content:"▾"'), css.count('content:"▸"') >= 1) == (0, True)


def test_a_numbered_page_counts_its_top_level_headings_and_shows_the_count_before_each_title() -> None:
    css = stylesheet()

    assert (
        ".wrap.numbered{counter-reset:skaldr-sec}" in css,
        ".wrap.numbered > h2{counter-increment:skaldr-sec;" in css,
        "content:counter(skaldr-sec, decimal-leading-zero)" in css,
    ) == (True, True, True)


def test_the_number_moves_into_the_left_margin_only_inside_a_wide_screen_query() -> None:
    css = stylesheet()
    wide_queries = re.findall(r"@media \(min-width:\d+px\)\{", css)
    wide_blocks = [block_opened_by(css, query) for query in wide_queries]
    margin_number = ".wrap.numbered > h2::before{position:absolute"

    assert (
        margin_number in css.replace("".join(wide_blocks), ""),
        any(margin_number in b for b in wide_blocks),
    ) == (
        False,
        True,
    )


def test_only_a_numbered_page_reads_the_section_counter() -> None:
    css = stylesheet()
    numbered_rules = css[css.index("\t.wrap.numbered{counter-reset") : css.index("\t/* Glow:")]
    elsewhere = css.replace(numbered_rules, "")

    assert ("skaldr-sec" in numbered_rules, "skaldr-sec" in elsewhere) == (True, False)
