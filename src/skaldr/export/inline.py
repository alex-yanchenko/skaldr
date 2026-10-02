import re
from dataclasses import replace

from skaldr.richtext import AnchorLink, Code, Link, Plain, Rich, RichContext, Run, Styled, parse_rich

WHITESPACE_RUN = re.compile(r"\s+")


def one_line(text: str) -> str:
    return " ".join(text.split())


def plain(text: str) -> Rich:
    collapsed = one_line(text)
    return (Plain(collapsed),) if collapsed else ()


def bold(text: str) -> Rich:
    runs = plain(text)
    return (Styled("bold", runs),) if runs else ()


def italic(runs: Rich) -> Rich:
    return (Styled("italic", runs),) if runs else ()


def labelled(label: str) -> Rich:
    name = one_line(label).removesuffix(":").rstrip()
    return (*bold(name), Plain(": ")) if name else ()


def _on_one_line(run: Run) -> Run:
    match run:
        case Plain():
            return Plain(WHITESPACE_RUN.sub(" ", run.text))
        case Code():
            return Code(" ".join(run.text.splitlines()))
        case Link() | AnchorLink():
            return replace(run, label=tuple(map(_on_one_line, run.label)))
        case Styled():
            return Styled(run.style, tuple(map(_on_one_line, run.runs)))
        case _:
            return run


def _trimmed(runs: Rich) -> Rich:
    if runs and isinstance(runs[0], Plain):
        runs = (Plain(runs[0].text.lstrip()), *runs[1:])
    if runs and isinstance(runs[-1], Plain):
        runs = (*runs[:-1], Plain(runs[-1].text.rstrip()))
    return tuple(run for run in runs if not (isinstance(run, Plain) and not run.text))


def rich_line(text: str, context: RichContext) -> Rich:
    return _trimmed(tuple(map(_on_one_line, parse_rich(text, context))))
