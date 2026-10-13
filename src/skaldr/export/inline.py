import re
from dataclasses import replace

from skaldr.richtext import (
    AnchorLink,
    Code,
    DateMention,
    DocumentLink,
    InlineMath,
    IssueLink,
    Link,
    PersonMention,
    Plain,
    Rich,
    RichContext,
    Run,
    Styled,
    Tinted,
    parse_rich,
)

WHITESPACE_RUN = re.compile(r"\s+")
LINE_ENDING = re.compile(r"\r\n?|\n")


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


def _on_one_line(run: Run) -> Run:
    match run:
        case Plain():
            return Plain(WHITESPACE_RUN.sub(" ", run.text))
        case Code():
            return Code(LINE_ENDING.sub(" ", run.text))
        case InlineMath():
            return InlineMath(LINE_ENDING.sub(" ", run.expression))
        case Link() | AnchorLink() | DateMention() | PersonMention() | IssueLink() | DocumentLink():
            return replace(run, label=tuple(map(_on_one_line, run.label)))
        case Styled() | Tinted():
            return replace(run, runs=tuple(map(_on_one_line, run.runs)))
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
