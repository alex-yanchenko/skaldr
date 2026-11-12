import re


def exactly(message: str) -> str:
    return f"^{re.escape(message)}$"
