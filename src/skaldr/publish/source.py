from typing import Any, cast

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from skaldr.errors import ReportError

PUBLISH_KEY = "publish"
CANNOT_CUT = (
    "the publish block could not be left out of the page: write it as its own top-level `publish:` key "
    "on its own lines, sharing no YAML anchors or merge keys with the rest of the document"
)


class _ComparableLoader(yaml.SafeLoader):
    pass


def _include_marker(loader: yaml.SafeLoader, node: yaml.Node) -> tuple[str, Any]:
    if isinstance(node, ScalarNode):
        return ("!include", loader.construct_scalar(node))
    return ("!include", node.start_mark.line)


_ComparableLoader.add_constructor("!include", _include_marker)


def _unreadable(exc: BaseException) -> ReportError:
    return ReportError(f"the source could not be read to leave its publish block out of the page: {exc}")


def _document(source: str) -> object:
    try:
        return cast(object, yaml.load(source, Loader=_ComparableLoader))
    except (yaml.YAMLError, RecursionError) as exc:
        raise _unreadable(exc) from exc


def _root_mapping(source: str) -> MappingNode | None:
    try:
        root: Node | None = yaml.SafeLoader(source).get_single_node()
    except yaml.YAMLError as exc:
        raise _unreadable(exc) from exc
    return root if isinstance(root, MappingNode) else None


def _is_publish_key(key: Node) -> bool:
    return isinstance(key, ScalarNode) and key.value == PUBLISH_KEY


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _first_line_after(node: Node) -> int:
    return node.end_mark.line + (1 if node.end_mark.column > 0 else 0)


def _first_line_after_content(node: Node) -> int:
    last_line = 0
    pending, visited = [node], set[int]()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, ScalarNode):
            last_line = max(last_line, _first_line_after(current))
        elif isinstance(current, MappingNode):
            pending += [child for pair in current.value for child in pair]
        elif isinstance(current, SequenceNode):
            pending += current.value
        last_line = max(last_line, current.start_mark.line + 1)
    return last_line


def _leading_comments_start(lines: list[str], key_line: int, floor: int) -> int:
    start = key_line
    while start > floor and _is_blank_or_comment(lines[start - 1]):
        start -= 1
    return start


def _publish_line_spans(root: MappingNode, lines: list[str]) -> list[range]:
    pairs: list[tuple[Node, Node]] = root.value
    floors = [0] + [_first_line_after_content(value) for _, value in pairs[:-1]]
    end_lines = [key.start_mark.line for key, _ in pairs[1:]] + [len(lines)]
    return [
        range(_leading_comments_start(lines, key.start_mark.line, floor), end_line)
        for (key, _), floor, end_line in zip(pairs, floors, end_lines, strict=True)
        if _is_publish_key(key) and end_line > key.start_mark.line
    ]


def _cut(source: str) -> str:
    root = _root_mapping(source)
    if root is None:
        return source
    lines = source.splitlines(keepends=True)
    dropped = {line for span in _publish_line_spans(root, lines) for line in span}
    return "".join(line for number, line in enumerate(lines) if number not in dropped)


def _canonical_text(value: object) -> str:
    return yaml.dump(value, allow_unicode=True)


def same_documents(left: object, right: object) -> bool:
    return _canonical_text(left) == _canonical_text(right)


def without_publish_block(source: str) -> str:
    original = _document(source)
    if not isinstance(original, dict):
        return source
    document = cast("dict[object, object]", original)
    if PUBLISH_KEY not in document:
        return source
    expected = {key: value for key, value in document.items() if key != PUBLISH_KEY}
    stripped = _cut(source)
    try:
        matches = same_documents(_document(stripped), expected)
    except (ReportError, RecursionError):
        matches = False
    if not matches:
        raise ReportError(CANNOT_CUT)
    return stripped
