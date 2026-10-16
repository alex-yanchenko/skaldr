import re

from skaldr.models import package_text

AA_TEXT_CONTRAST = 4.5
LIGHT = 0
DARK = 1


def _declarations(css: str) -> dict[str, str]:
    root = css[css.index(":root{") :]
    return dict(
        re.findall(r"(--[\w-]+):\s*((?:light-dark\((?:[^()]|\([^()]*\))*\))|[^;]+?)\s*(?:;|\n|$)", root)
    )


def _resolve(declarations: dict[str, str], name: str, theme: int) -> str:
    value = declarations[name]
    reference = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if reference:
        return _resolve(declarations, reference.group(1), theme)
    pair = re.fullmatch(r"light-dark\((#[0-9a-fA-F]{6}),\s*(#[0-9a-fA-F]{6})\)", value)
    if pair:
        return pair.group(theme + 1)
    return value


def _luminance(colour: str) -> float:
    channels = [int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _token_names(declarations: dict[str, str]) -> list[str]:
    return sorted(name for name in declarations if name.startswith("--tok-"))


def test_every_code_token_colour_reads_at_aa_contrast_on_the_code_background_in_both_themes() -> None:
    declarations = _declarations(package_text("styles.css"))
    contrasts = {
        (name, theme_name): _contrast(
            _resolve(declarations, name, theme), _resolve(declarations, "--code-bg", theme)
        )
        for name in _token_names(declarations)
        for theme_name, theme in (("light", LIGHT), ("dark", DARK))
    }

    assert {key: round(ratio, 2) for key, ratio in contrasts.items() if ratio < AA_TEXT_CONTRAST} == {}
