HTTP_TIMEOUT_SECONDS = 30.0


def printable(text: str) -> str:
    return "".join(character for character in text if character.isprintable())
