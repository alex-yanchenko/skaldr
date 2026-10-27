import re

from skaldr.models import package_path

TINT_PAIR = re.compile(
    r"light-dark\(color-mix\(in srgb, (?P<colour>[^%]+?) (?P<light>[\d.]+)%, transparent\), "
    r"color-mix\(in srgb, (?P=colour) (?P<dark>[\d.]+)%, transparent\)\)"
)


def stylesheet() -> str:
    return package_path("styles.css").read_text(encoding="utf-8")


def glow_strengths() -> list[tuple[str, float, float]]:
    return [
        (pair["colour"], float(pair["light"]), float(pair["dark"]))
        for pair in TINT_PAIR.finditer(stylesheet())
        if pair["colour"] != "var(--ink)"
    ]


def test_every_glow_pairs_a_light_strength_with_a_dark_one() -> None:
    assert glow_strengths() == [
        ("var(--t,var(--line))", 14.0, 9.0),
        ("var(--t,var(--accent-fg))", 9.0, 4.0),
        ("var(--c)", 7.0, 3.0),
        ("var(--accent-fg)", 8.0, 5.0),
        ("var(--accent-fg)", 5.0, 2.5),
        ("var(--m,var(--neutral-fg))", 35.0, 18.0),
        ("currentColor", 10.0, 5.0),
    ]


def test_the_glow_in_dark_is_at_most_two_thirds_of_the_glow_in_light() -> None:
    assert [(colour, light, dark) for colour, light, dark in glow_strengths() if dark > light * 2 / 3] == []


MOTION_QUERY = "@media screen and (prefers-reduced-motion: no-preference){"


def motion_blocks() -> list[str]:
    css = stylesheet()
    blocks: list[str] = []
    start = css.find(MOTION_QUERY)
    while start != -1:
        depth = 1
        cursor = start + len(MOTION_QUERY)
        while depth:
            depth += {"{": 1, "}": -1}.get(css[cursor], 0)
            cursor += 1
        blocks.append(css[start + len(MOTION_QUERY) : cursor - 1])
        start = css.find(MOTION_QUERY, cursor)
    return blocks


def stylesheet_without_motion() -> str:
    css = stylesheet()
    for block in motion_blocks():
        css = css.replace(MOTION_QUERY + block + "}", "")
    return css


def test_all_motion_sits_in_one_screen_only_block_for_readers_who_allow_it() -> None:
    assert len(motion_blocks()) == 1


def test_nothing_animates_outside_that_block() -> None:
    outside = stylesheet_without_motion()

    assert [word for word in ("@keyframes", "animation", "transition") if word in outside] == []


def test_the_animations_are_these_keyframes() -> None:
    assert sorted(re.findall(r"@keyframes (\S+?)\{", motion_blocks()[0])) == [
        "skaldr-draw",
        "skaldr-fade",
        "skaldr-fill",
        "skaldr-grow",
        "skaldr-line",
        "skaldr-read",
        "skaldr-rise",
        "skaldr-shine",
        "skaldr-spin",
    ]


def test_only_the_hover_border_spins_on_a_timer_and_every_other_animation_follows_the_scroll() -> None:
    motion = motion_blocks()[0]
    driven_by_scroll = re.findall(
        r"animation:(\S+)[^;}]*;\s*animation-timeline:(?:view\(\)|scroll\(root\))", motion
    )
    declared = re.findall(r"[^-]animation:(\S+)", motion)

    assert sorted(set(declared) - set(driven_by_scroll)) == ["skaldr-spin"]


def test_no_animation_waits_before_it_starts() -> None:
    assert "animation-delay" not in stylesheet()


def test_no_easing_overshoots() -> None:
    curves = re.findall(r"cubic-bezier\(([^)]*)\)", stylesheet())
    overshooting = [
        curve for curve in curves if not all(0.0 <= float(value) <= 1.0 for value in curve.split(",")[1::2])
    ]

    assert (curves != [], overshooting) == (True, [])


def test_the_hover_lift_is_two_pixels_over_450_milliseconds() -> None:
    motion = motion_blocks()[0]

    assert "transition:transform .45s" in motion
    assert ":hover{transform:translateY(-2px)}" in motion


def test_the_contents_panel_lights_the_section_in_view_by_scroll_tracking() -> None:
    css = stylesheet()

    assert ("scroll-target-group:auto" in css, ".toc-pop a:target-current{" in css) == (True, True)


def test_the_corner_row_holding_both_buttons_and_the_panel_is_hidden_on_paper() -> None:
    printed = stylesheet().split("@layer print {", 1)[1]

    assert ".sc,.skaldr-live{display:none}" in printed


def test_scroll_driven_rules_wait_for_a_browser_that_supports_them() -> None:
    assert "@supports (animation-timeline: view()){" in motion_blocks()[0]
