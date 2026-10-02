HTTP_TIMEOUT_SECONDS = 30.0


def without_control_characters(text: str) -> str:
    return "".join(character for character in text if character.isprintable())
