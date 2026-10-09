import json
import types
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Union, get_args, get_origin

from markdown_it import MarkdownIt
from markdown_it.token import Token
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import to_jsonable_python

from skaldr.errors import UnknownGuideTopicError
from skaldr.models import Block

BLOCKS_SECTION = "Blocks"
TABLE_HEADER_LINES = 2
NONE_TYPE = type(None)


@dataclass(frozen=True)
class _Section:
    title: str
    first_line: int
    end_line: int


def _block_models() -> dict[str, type[BaseModel]]:
    union = get_args(Block)[0]
    models: dict[str, type[BaseModel]] = {}
    for model in get_args(union):
        (name,) = get_args(model.model_fields["type"].annotation)
        models.setdefault(name, model)
    return models


def block_names() -> tuple[str, ...]:
    return tuple(_block_models())


def _type_name(annotation: object) -> str:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if annotation is NONE_TYPE:
        return "null"
    if origin is Annotated:
        return _type_name(arguments[0])
    if origin is Union or origin is types.UnionType:
        return " | ".join(_type_name(argument) for argument in arguments)
    if origin is Literal:
        return " | ".join(str(argument) for argument in arguments)
    if origin is not None:
        return f"{origin.__name__}[{', '.join(_type_name(argument) for argument in arguments)}]"
    return getattr(annotation, "__name__", str(annotation))


def _field_line(name: str, field: FieldInfo) -> str:
    requirement = (
        "required"
        if field.is_required()
        else f"default {json.dumps(to_jsonable_python(field.get_default(call_default_factory=True)))}"
    )
    description = f". {field.description}" if field.description else ""
    return f"  {name}: {_type_name(field.annotation)}, {requirement}{description}"


def block_fields(name: str) -> str:
    fields = [
        _field_line(field_name, field)
        for field_name, field in _block_models()[name].model_fields.items()
        if field_name != "type"
    ]
    return "\n".join(["Fields", *fields])


def _parse(guide: str) -> list[Token]:
    return MarkdownIt("commonmark").enable("table").parse(guide)


def _sections(tokens: Sequence[Token], line_count: int) -> list[_Section]:
    headings = [
        (token.map[0], tokens[index + 1].content)
        for index, token in enumerate(tokens)
        if token.type == "heading_open" and token.tag == "h2" and token.map is not None
    ]
    ends = [first for first, _title in headings[1:]] + [line_count]
    return [_Section(title, first, end) for (first, title), end in zip(headings, ends, strict=True)]


def section_titles(guide: str) -> list[str]:
    return [section.title for section in _sections(_parse(guide), len(guide.splitlines()))]


def _section_text(guide: str, title: str) -> str | None:
    lines = guide.splitlines()
    for section in _sections(_parse(guide), len(lines)):
        if section.title == title:
            return "\n".join(lines[section.first_line : section.end_line]).rstrip()
    return None


def _first_cell_code(tokens: Sequence[Token], row_index: int) -> str | None:
    cell = tokens[row_index + 1]
    inline = tokens[row_index + 2]
    if cell.type not in ("th_open", "td_open") or not inline.children:
        return None
    first = inline.children[0]
    return first.content if first.type == "code_inline" else None


def _blocks_table_rows(guide: str, name: str) -> str | None:
    lines = guide.splitlines()
    tokens = _parse(guide)
    blocks = next(
        (section for section in _sections(tokens, len(lines)) if section.title == BLOCKS_SECTION), None
    )
    if blocks is None:
        return None
    table_first_line = blocks.first_line
    for index, token in enumerate(tokens):
        if token.map is None or token.map[0] < blocks.first_line:
            continue
        if token.map[0] >= blocks.end_line:
            return None
        if token.type == "table_open":
            table_first_line = token.map[0]
        if token.type == "tr_open" and _first_cell_code(tokens, index) == name:
            header = lines[table_first_line : table_first_line + TABLE_HEADER_LINES]
            return "\n".join([*header, *lines[token.map[0] : token.map[1]]])
    return None


def describe_block(
    name: str,
    guide: str,
    *,
    names: Sequence[str],
    fields_of: Callable[[str], str],
) -> str:
    if name not in names:
        raise UnknownGuideTopicError(f"unknown block '{name}'; the blocks are {', '.join(names)}")
    parts = [
        _blocks_table_rows(guide, name),
        _section_text(guide, f"The `{name}`"),
        fields_of(name),
    ]
    return "\n\n".join(part for part in parts if part)


def list_topics(guide: str, *, names: Sequence[str]) -> str:
    return "\n".join(["Guide sections", *section_titles(guide), "", "Blocks", *names])
