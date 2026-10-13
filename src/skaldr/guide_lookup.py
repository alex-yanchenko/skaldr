import json
import types
from dataclasses import dataclass
from typing import Annotated, ForwardRef, Literal, Union, get_args, get_origin

from markdown_it import MarkdownIt
from markdown_it.token import Token
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import to_jsonable_python

from skaldr import models
from skaldr.errors import UnknownGuideTopicError
from skaldr.models import Block

_BLOCKS_SECTION = "Blocks"
_TABLE_HEADER_LINES = 2
_NONE_TYPE = type(None)
_BLOCK_TYPE_FIELD = "type"
_INDENT = "  "


@dataclass(frozen=True)
class _Section:
    title: str
    first_line: int
    end_line: int


def _block_models() -> dict[str, type[BaseModel]]:
    models: dict[str, type[BaseModel]] = {}
    for model in get_args(get_args(Block)[0]):
        (name,) = get_args(model.model_fields[_BLOCK_TYPE_FIELD].annotation)
        models.setdefault(name, model)
    return models


def block_names() -> tuple[str, ...]:
    return tuple(_block_models())


def _is_block_model(annotation: object) -> bool:
    if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
        return False
    type_field = annotation.model_fields.get(_BLOCK_TYPE_FIELD)
    if type_field is None or get_origin(type_field.annotation) is not Literal:
        return False
    return get_args(type_field.annotation)[0] in _block_models()


def _resolved(annotation: object) -> object:
    name = annotation.__forward_arg__ if isinstance(annotation, ForwardRef) else annotation
    return getattr(models, name, annotation) if isinstance(name, str) else annotation


def _is_block_union(arguments: tuple[object, ...]) -> bool:
    return len(arguments) > 1 and all(_is_block_model(argument) for argument in arguments)


def _type_name(unresolved: object) -> str:
    annotation = _resolved(unresolved)
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if annotation is _NONE_TYPE:
        return "null"
    if origin is Annotated:
        return _type_name(arguments[0])
    if origin is Union or origin is types.UnionType:
        if _is_block_union(arguments):
            return "Block"
        return " | ".join(_type_name(argument) for argument in arguments)
    if origin is Literal:
        return " | ".join(repr(argument) for argument in arguments)
    if origin is not None:
        return f"{origin.__name__}[{', '.join(_type_name(argument) for argument in arguments)}]"
    return getattr(annotation, "__name__", str(annotation))


def _nested_models(unresolved: object) -> list[type[BaseModel]]:
    annotation = _resolved(unresolved)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [] if _is_block_model(annotation) else [annotation]
    arguments = get_args(annotation)
    if _is_block_union(arguments):
        return []
    found: list[type[BaseModel]] = []
    for argument in arguments:
        for model in _nested_models(argument):
            if model not in found:
                found.append(model)
    return found


def _field_line(name: str, field: FieldInfo, indent: str) -> str:
    requirement = (
        "required"
        if field.is_required()
        else f"default {json.dumps(to_jsonable_python(field.get_default(call_default_factory=True)))}"
    )
    description = f". {field.description}" if field.description else ""
    return f"{indent}{name}: {_type_name(field.annotation)}, {requirement}{description}"


def _model_field_lines(model: type[BaseModel], indent: str, *, expand: bool) -> list[str]:
    lines: list[str] = []
    for name, field in model.model_fields.items():
        if name == _BLOCK_TYPE_FIELD and indent == _INDENT:
            continue
        lines.append(_field_line(name, field, indent))
        if expand:
            for nested in _nested_models(field.annotation):
                lines.extend(_model_field_lines(nested, indent * 2, expand=False))
    return lines


def _fields_text(name: str) -> str:
    return "\n".join(["Fields", *_model_field_lines(_block_models()[name], _INDENT, expand=True)])


def _plain(title: str) -> str:
    return title.replace("`", "").strip()


@dataclass(frozen=True)
class _Guide:
    lines: list[str]
    tokens: list[Token]
    sections: list[_Section]

    @classmethod
    def parse(cls, text: str) -> "_Guide":
        lines = text.splitlines()
        tokens = MarkdownIt("commonmark").enable("table").parse(text)
        headings = [
            (token.map[0], tokens[index + 1].content)
            for index, token in enumerate(tokens)
            if token.type == "heading_open" and token.tag == "h2" and token.map is not None
        ]
        ends = [first for first, _title in headings[1:]] + [len(lines)]
        sections = [_Section(title, first, end) for (first, title), end in zip(headings, ends, strict=True)]
        return cls(lines, tokens, sections)

    def section_text(self, section: _Section) -> str:
        return "\n".join(self.lines[section.first_line : section.end_line]).rstrip()

    def section_named(self, title: str) -> _Section | None:
        return next((section for section in self.sections if section.title == title), None)

    def section_matching(self, query: str) -> _Section | None:
        wanted = _plain(query).casefold()
        exact = [section for section in self.sections if _plain(section.title).casefold() == wanted]
        if exact:
            return exact[0]
        prefixed = [
            section for section in self.sections if _plain(section.title).casefold().startswith(wanted)
        ]
        return prefixed[0] if len(prefixed) == 1 and wanted else None

    def blocks_table_rows(self, name: str) -> str | None:
        blocks = self.section_named(_BLOCKS_SECTION)
        if blocks is None:
            return None
        table_first_line = blocks.first_line
        for index, token in enumerate(self.tokens):
            if token.map is None or token.map[0] < blocks.first_line:
                continue
            if token.map[0] >= blocks.end_line:
                return None
            if token.type == "table_open":
                table_first_line = token.map[0]
            if token.type == "tr_open" and self._first_cell_code(index) == name:
                header = self.lines[table_first_line : table_first_line + _TABLE_HEADER_LINES]
                return "\n".join([*header, *self.lines[token.map[0] : token.map[1]]])
        return None

    def _first_cell_code(self, row_index: int) -> str | None:
        cell = self.tokens[row_index + 1]
        inline = self.tokens[row_index + 2]
        if cell.type not in ("th_open", "td_open") or not inline.children:
            return None
        first = inline.children[0]
        return first.content if first.type == "code_inline" else None


def _describe_block(name: str, guide: _Guide) -> str:
    section = guide.section_named(f"The `{name}`")
    parts = [
        guide.blocks_table_rows(name),
        guide.section_text(section) if section else None,
        _fields_text(name),
    ]
    return "\n\n".join(part for part in parts if part)


def is_topic(name: str, guide_text: str) -> bool:
    return name in block_names() or _Guide.parse(guide_text).section_matching(name) is not None


def lookup(name: str, guide_text: str) -> str:
    guide = _Guide.parse(guide_text)
    if name in block_names():
        return _describe_block(name, guide)
    section = guide.section_matching(name)
    if section is None:
        raise UnknownGuideTopicError(
            f"unknown block or section '{name}'; the blocks are {', '.join(block_names())}; "
            f"the sections are {', '.join(_plain(item.title) for item in guide.sections)}"
        )
    return guide.section_text(section)


def list_topics(guide_text: str) -> str:
    guide = _Guide.parse(guide_text)
    return "\n".join(
        ["Guide sections", *(section.title for section in guide.sections), "", "Blocks", *block_names()]
    )
