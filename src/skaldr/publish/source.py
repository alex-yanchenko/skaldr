from collections.abc import Iterator

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from skaldr.errors import ReportError

PUBLISH_KEY = "publish"
OWN_LINES_REQUIRED = (
    "a publish block must be its own top-level key on its own lines to be left out of the page"
)


def _compose(source: str) -> Node | None:
    loader = yaml.SafeLoader(source)
    try:
        return loader.get_single_node()
    except yaml.YAMLError as exc:
        raise ReportError(
            f"the source could not be read to leave its publish block out of the page: {exc}"
        ) from exc


def _subtree(node: Node) -> Iterator[Node]:
    yield node
    if isinstance(node, MappingNode):
        for key, value in node.value:
            yield from _subtree(key)
            yield from _subtree(value)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            yield from _subtree(item)


def _is_publish_key(key: Node) -> bool:
    return isinstance(key, ScalarNode) and key.value == PUBLISH_KEY


def _publish_line_spans(root: MappingNode, line_count: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for index, (key, _) in enumerate(root.value):
        if _is_publish_key(key):
            following = (
                root.value[index + 1][0].start_mark.line if index + 1 < len(root.value) else line_count
            )
            if following == key.start_mark.line:
                raise ReportError(OWN_LINES_REQUIRED)
            spans.append((key.start_mark.line, following))
    return spans


def _refuse_anchors_shared_outside(root: MappingNode) -> None:
    inside: set[int] = set()
    outside: list[Node] = []
    for key, value in root.value:
        if _is_publish_key(key):
            inside |= {id(node) for node in _subtree(value)}
        else:
            outside += list(_subtree(value))
    if any(id(node) in inside for node in outside):
        raise ReportError(
            "the publish block defines a YAML anchor another key uses, so it cannot be left out of the page"
        )


def _has_publish_key(source: str) -> bool:
    root = _compose(source)
    return isinstance(root, MappingNode) and any(_is_publish_key(key) for key, _ in root.value)


def without_publish_block(source: str) -> str:
    if PUBLISH_KEY not in source:
        return source
    root = _compose(source)
    if not isinstance(root, MappingNode):
        return source
    lines = source.splitlines(keepends=True)
    spans = _publish_line_spans(root, len(lines))
    if not spans:
        return source
    if root.flow_style:
        raise ReportError(OWN_LINES_REQUIRED)
    _refuse_anchors_shared_outside(root)
    dropped = {line for start, end in spans for line in range(start, end)}
    stripped = "".join(line for number, line in enumerate(lines) if number not in dropped)
    if _has_publish_key(stripped):
        raise ReportError("the publish block could not be left out of the page")
    return stripped
