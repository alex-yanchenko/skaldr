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
