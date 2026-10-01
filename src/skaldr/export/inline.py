import re

from skaldr.richtext import Plain, Rich, RichContext, Styled, parse_rich

WHITESPACE_RUN = re.compile(r"\s+")


def one_line(text: str) -> str:
    return " ".join(text.split())


def plain(text: str) -> Rich:
    collapsed = WHITESPACE_RUN.sub(" ", text)
    return (Plain(collapsed),) if collapsed else ()


def bold(text: str) -> Rich:
    runs = plain(text)
    return (Styled("bold", runs),) if runs else ()


def italic(runs: Rich) -> Rich:
    return (Styled("italic", runs),) if runs else ()


def labelled(label: str) -> Rich:
    return bold(one_line(label).removesuffix(":").rstrip()) + plain(": ")


def rich_line(text: str, context: RichContext) -> Rich:
    return parse_rich(one_line(text), context)


def paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]
