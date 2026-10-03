import pytest

from skaldr.auth import printable_only


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("Acme Corp", "Acme Corp"),
        ("Acme\N{NO-BREAK SPACE}Corp", "Acme Corp"),
        ("Acme\N{IDEOGRAPHIC SPACE}Corp", "Acme Corp"),
        ("Acme\N{EM SPACE}Corp\N{NARROW NO-BREAK SPACE}Ltd", "Acme Corp Ltd"),
        ("\N{ZERO WIDTH NON-JOINER}\N{ZERO WIDTH JOINER}", "\N{ZERO WIDTH NON-JOINER}\N{ZERO WIDTH JOINER}"),
        ("Acme\x1b[2J\x07\r\n\tCorp", "Acme[2JCorp"),
        ("Acme\x85\x9bCorp", "AcmeCorp"),
        (
            "\N{LEFT-TO-RIGHT EMBEDDING}\N{RIGHT-TO-LEFT EMBEDDING}\N{POP DIRECTIONAL FORMATTING}"
            "\N{LEFT-TO-RIGHT OVERRIDE}\N{RIGHT-TO-LEFT OVERRIDE}Acme",
            "Acme",
        ),
        (
            "\N{LEFT-TO-RIGHT ISOLATE}\N{RIGHT-TO-LEFT ISOLATE}\N{FIRST STRONG ISOLATE}"
            "\N{POP DIRECTIONAL ISOLATE}Acme",
            "Acme",
        ),
    ],
    ids=[
        "plain text",
        "a no-break space",
        "an ideographic space",
        "other space separators",
        "zero width non-joiner and joiner",
        "c0 controls",
        "c1 controls",
        "bidi embeddings and overrides",
        "bidi isolates",
    ],
)
def test_printable_only_keeps_words_and_joiners_and_drops_controls(text: str, shown: str) -> None:
    assert printable_only(text) == shown
