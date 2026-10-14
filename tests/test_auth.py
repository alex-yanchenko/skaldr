import pytest

from skaldr.auth import CaughtWithoutChaining, printable_only


class SiteRefusedError(ValueError):
    pass


def test_caught_without_chaining_catches_the_named_type() -> None:
    refused = ValueError("refused")

    with CaughtWithoutChaining(ValueError) as caught:
        raise refused

    assert caught.error is refused


def test_caught_without_chaining_catches_a_subclass_of_the_named_type() -> None:
    refused = SiteRefusedError("refused")

    with CaughtWithoutChaining(ValueError) as caught:
        raise refused

    assert caught.error is refused


def test_caught_without_chaining_lets_an_unrelated_exception_through() -> None:
    with pytest.raises(TypeError, match=r"^unrelated$"), CaughtWithoutChaining(ValueError):
        raise TypeError("unrelated")


def test_caught_without_chaining_has_no_error_when_nothing_was_raised() -> None:
    with CaughtWithoutChaining(ValueError) as caught:
        pass

    with pytest.raises(AssertionError, match=r"^no ValueError was caught$"):
        _ = caught.error


def test_an_error_raised_after_the_block_carries_no_chain() -> None:
    with CaughtWithoutChaining(ValueError) as caught:
        raise ValueError("secret-value")

    with pytest.raises(RuntimeError) as raised:
        raise RuntimeError(f"refused: {type(caught.error).__name__}")

    assert (str(raised.value), raised.value.__cause__, raised.value.__context__) == (
        "refused: ValueError",
        None,
        None,
    )


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("Acme Corp", "Acme Corp"),
        ("Acme\N{NO-BREAK SPACE}Corp", "Acme Corp"),
        ("Acme\N{IDEOGRAPHIC SPACE}Corp", "Acme Corp"),
        ("Acme\N{EM SPACE}Corp\N{NARROW NO-BREAK SPACE}Ltd", "Acme Corp Ltd"),
        ("\N{ZERO WIDTH NON-JOINER}\N{ZERO WIDTH JOINER}", "\N{ZERO WIDTH NON-JOINER}\N{ZERO WIDTH JOINER}"),
        ("Acme\x1b[2J\x07Corp", "Acme[2JCorp"),
        ("Acme\x9bCorp", "AcmeCorp"),
        ("Acme\r\n\tCorp\x85Ltd\N{LINE SEPARATOR}Inc", "Acme Corp Ltd Inc"),
        ("  Acme \N{NO-BREAK SPACE}  Corp\n", "Acme Corp"),
        ("\x07 Acme \x1b \x07", "Acme"),
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
        "line breaks and tabs between words",
        "runs of whitespace and whitespace at the ends",
        "controls beside the whitespace at the ends",
        "bidi embeddings and overrides",
        "bidi isolates",
    ],
)
def test_printable_only_keeps_words_apart_and_drops_controls(text: str, shown: str) -> None:
    assert printable_only(text) == shown
