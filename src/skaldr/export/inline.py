import re
from dataclasses import replace

from skaldr.richtext import AnchorLink, Code, Link, Plain, Rich, RichContext, Run, Styled, parse_rich

WHITESPACE_RUN = re.compile(r"\s+")


def plain(text: str) -> Rich:
    collapsed = WHITESPACE_RUN.sub(" ", text)
    return (Plain(collapsed),) if collapsed else ()


def bold(text: str) -> Rich:
    runs = plain(text)
    return (Styled("bold", runs),) if runs else ()


def italic(runs: Rich) -> Rich:
    return (Styled("italic", runs),) if runs else ()


def _on_one_line(run: Run) -> Run:
    match run:
        case Plain():
            return Plain(WHITESPACE_RUN.sub(" ", run.text))
        case Code():
            return Code(run.text.replace("\n", " "))
        case Link() | AnchorLink():
            return replace(run, label=tuple(map(_on_one_line, run.label)))
        case Styled():
            return Styled(run.style, tuple(map(_on_one_line, run.runs)))
        case _:
            return run


def _trimmed(runs: list[Run]) -> Rich:
    if runs and isinstance(runs[0], Plain):
        runs[0] = Plain(runs[0].text.lstrip())
    if runs and isinstance(runs[-1], Plain):
        runs[-1] = Plain(runs[-1].text.rstrip())
    return tuple(run for run in runs if not (isinstance(run, Plain) and not run.text))


def rich_line(text: str, context: RichContext) -> Rich:
    return _trimmed([_on_one_line(run) for run in parse_rich(text, context)])


def paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]
