import ast
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from markdown_it import MarkdownIt
from pydantic import JsonValue, TypeAdapter, ValidationError

from skaldr.export import ExportTarget
from skaldr.models import AnyBlock, Report, package_text, parse_report
from skaldr.render import render_html
from tests.conftest import REPO_ROOT
from tests.factories.report_factory import make_report

GUIDE = package_text("skill/GUIDE.md")
SKILL = package_text("skill/SKILL.md")
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

_YAML_INFO = ("yaml", "yml")
_PLACEHOLDERS = ("...", "…")
_MAPPING = TypeAdapter(dict[str, Any])
_BLOCK_LIST = TypeAdapter(list[dict[str, Any]])
_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)

_GUIDE_BADGES = {
    key: {"label": key.title(), "tone": "slate", "legend": f"{key.title()} in a guide example."}
    for key in ("FLOOR", "SYSTEM", "HAVE", "GAP", "HIGH", "LOW")
}


@dataclass(frozen=True)
class GuideExample:
    line: int
    text: str

    @property
    def opening(self) -> str:
        return next(iter(self.text.splitlines()), "")


@dataclass(frozen=True)
class Skeleton:
    reason: str
    as_document: Callable[[JsonValue], JsonValue]


def _whole_document(data: JsonValue) -> JsonValue:
    return data


def _block_list(data: JsonValue) -> JsonValue:
    return {"blocks": data}


def _swimlane_fields(data: JsonValue) -> JsonValue:
    return {"blocks": [{"type": "swimlane", **_MAPPING.validate_python(data)}]}


def _table_columns(data: JsonValue) -> JsonValue:
    return {"blocks": [{"type": "table", "columns": data}]}


_SKELETONS = {
    "version: 1          # required, integer": Skeleton(
        "the Shape overview, where every value is a `{ ... }` or `[ ... ]` placeholder", _whole_document
    ),
    "meta:": Skeleton("a meta fragment with no blocks", _whole_document),
    "badges:": Skeleton("a badges fragment with no meta or blocks", _whole_document),
    "- type: cards            # a summary that can't go stale": Skeleton(
        "derived cards over a matrix whose rows, columns and cells are left out", _block_list
    ),
    "- type: grid": Skeleton("a grid whose cell blocks are `...` placeholders", _block_list),
    "columns:": Skeleton("the columns of a swimlane, shown without the swimlane", _swimlane_fields),
    '- { key: access, label: "Access", kind: badge, placement: cell, width: 1 }': Skeleton(
        "one table column, with the row it takes shown as a comment", _table_columns
    ),
    "badges: !include shared/badges.yaml   # a shared vocabulary across several reports": Skeleton(
        "an !include example naming fragment files that do not exist", _whole_document
    ),
    "publish:": Skeleton("a publish fragment naming sections the example does not define", _whole_document),
}


def _yaml_examples(guide: str) -> list[GuideExample]:
    fences = [token for token in MarkdownIt("commonmark").parse(guide) if token.type == "fence"]
    return [
        GuideExample(token.map[0] + 1 if token.map else 0, token.content)
        for token in fences
        if token.info.strip().split(maxsplit=1)[:1] in ([info] for info in _YAML_INFO)
    ]


_EXAMPLES = _yaml_examples(GUIDE)
_BUILDABLE = [example for example in _EXAMPLES if example.opening not in _SKELETONS]
_SKIPPED = [example for example in _EXAMPLES if example.opening in _SKELETONS]


class _PlaceholderLoader(yaml.SafeLoader):
    pass


def _include_placeholder(_loader: yaml.SafeLoader, _node: yaml.Node) -> None:
    return None


_PlaceholderLoader.add_constructor("!include", _include_placeholder)


def _without_placeholders(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: _without_placeholders(item) for key, item in value.items() if key not in _PLACEHOLDERS}
    if isinstance(value, list):
        return [_without_placeholders(item) for item in value if item not in _PLACEHOLDERS]
    return value


def _skeleton_document(text: str, as_document: Callable[[JsonValue], JsonValue]) -> JsonValue:
    data = _JSON.validate_python(yaml.load(text, Loader=_PlaceholderLoader))
    return as_document(_without_placeholders(data))


def _unknown_keys(document: JsonValue) -> list[tuple[str | int, ...]]:
    try:
        Report.model_validate(document)
    except ValidationError as error:
        return [tuple(detail["loc"]) for detail in error.errors() if detail["type"] == "extra_forbidden"]
    return []


def _as_document(example: GuideExample) -> dict[str, Any]:
    data = yaml.safe_load(example.text)
    if isinstance(data, list):
        return make_report(badges=_GUIDE_BADGES, blocks=_BLOCK_LIST.validate_python(data))
    return _MAPPING.validate_python(data)


def _top_level_keys_named_in(text: str) -> set[str]:
    sentence = re.search(r"^Top level is (.+?)nothing\s+else\.", text, re.MULTILINE | re.DOTALL)
    assert sentence is not None
    return set(re.findall(r"`(\w+)`", sentence.group(1)))


def _keys_of_the_shape_block(guide: str) -> set[str]:
    shape = re.search(r"^## Shape\n\n```yaml\n(.*?)^```", guide, re.MULTILINE | re.DOTALL)
    assert shape is not None
    return set(re.findall(r"^(\w+):", shape.group(1), re.MULTILINE))


@pytest.mark.parametrize("text", [pytest.param(GUIDE, id="guide"), pytest.param(README, id="readme")])
def test_the_top_level_sentence_names_every_top_level_key(text: str) -> None:
    assert _top_level_keys_named_in(text) == set(Report.model_fields)


def test_the_guide_shape_block_lists_every_top_level_key() -> None:
    assert _keys_of_the_shape_block(GUIDE) == set(Report.model_fields)


_DIVIDER = "- type: divider\n"


@pytest.mark.parametrize(
    ("markdown", "examples"),
    [
        pytest.param("```yaml\n- type: divider\n```\n", [GuideExample(1, _DIVIDER)], id="yaml"),
        pytest.param("```yml\n- type: divider\n```\n", [GuideExample(1, _DIVIDER)], id="yml"),
        pytest.param(
            "```yaml title=x\n- type: divider\n```\n", [GuideExample(1, _DIVIDER)], id="info-string"
        ),
        pytest.param("~~~yaml\n- type: divider\n~~~\n", [GuideExample(1, _DIVIDER)], id="tildes"),
        pytest.param("> ```yaml\n> - type: divider\n> ```\n", [GuideExample(1, _DIVIDER)], id="blockquote"),
        pytest.param(
            "- a\n\n  ```yaml\n  - type: divider\n  ```\n", [GuideExample(3, _DIVIDER)], id="list-item"
        ),
        pytest.param("```yamlish\n- type: divider\n```\n", [], id="other-language"),
        pytest.param("```bash\nskaldr --guide\n```\n", [], id="bash"),
    ],
)
def test_the_extractor_takes_every_yaml_fence(markdown: str, examples: list[GuideExample]) -> None:
    assert _yaml_examples(markdown) == examples


def test_an_empty_fence_has_an_empty_opening() -> None:
    assert GuideExample(1, "").opening == ""


def test_every_skipped_skeleton_is_still_in_the_guide() -> None:
    assert {example.opening for example in _SKIPPED} == set(_SKELETONS)


@pytest.mark.parametrize(
    "example", [pytest.param(example, id=f"line-{example.line}") for example in _SKIPPED]
)
def test_a_guide_skeleton_names_only_keys_the_models_define(example: GuideExample) -> None:
    skeleton = _SKELETONS[example.opening]

    assert _unknown_keys(_skeleton_document(example.text, skeleton.as_document)) == []


@pytest.mark.parametrize(
    ("text", "unknown"),
    [
        pytest.param('meta:\n  title: "T"\n  bogus_key: 1\n', [("meta", "bogus_key")], id="meta"),
        pytest.param(
            "publish:\n  doc_id: plan\n  bogus_key: 1\n  targets: []\n",
            [("publish", "bogus_key")],
            id="publish",
        ),
        pytest.param("bogus_key: 1\nblocks: [ ... ]\n", [("bogus_key",)], id="top-level"),
    ],
)
def test_the_skeleton_check_names_a_key_the_models_do_not_define(
    text: str, unknown: list[tuple[str | int, ...]]
) -> None:
    assert _unknown_keys(_skeleton_document(text, _whole_document)) == unknown


@pytest.mark.parametrize(
    "example", [pytest.param(example, id=f"line-{example.line}") for example in _BUILDABLE]
)
def test_a_guide_example_builds_when_copied(example: GuideExample) -> None:
    html = render_html(parse_report(_as_document(example)))

    assert html.startswith("<!doctype html>")


def _every_block_type() -> set[str]:
    return {get_args(model.model_fields["type"].annotation)[0] for model in get_args(AnyBlock)}


def _readme_block_list(readme: str) -> str:
    paragraph = re.search(r"^\*\*Blocks:\*\*(.*?)\n\n(?!- )", readme, re.MULTILINE | re.DOTALL)
    assert paragraph is not None
    return paragraph.group(1)


def test_the_readme_block_list_names_every_block_type() -> None:
    listed = _readme_block_list(README)

    assert {kind for kind in _every_block_type() if f"`{kind}`" not in listed} == set()


@pytest.mark.parametrize("text", [pytest.param(SKILL, id="skill"), pytest.param(README, id="readme")])
def test_the_skill_and_the_readme_name_both_export_targets(text: str) -> None:
    named = {target for target in get_args(ExportTarget) if f"--export {target}" in text}

    assert named == set(get_args(ExportTarget))


_EM_OR_EN_DASH = re.compile("[\N{EM DASH}\N{EN DASH}]")
_TEMPLATE_COMMENT = re.compile(r"\{#.*?#\}|<!--.*?-->|/\*.*?\*/", re.DOTALL)

_SHIPPED_PROSE = (
    "README.md",
    "AGENTS.md",
    "data/example.yaml",
    "examples/sales-pipeline.yaml",
    "src/skaldr/skill/GUIDE.md",
    "src/skaldr/skill/SKILL.md",
    "src/skaldr/skill/example.yaml",
)


def _docstrings_of(tree: ast.Module) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, owners)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }


def _string_literals_with_a_dash(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstrings_of(tree)
    return [
        f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and _EM_OR_EN_DASH.search(node.value)
    ]


@pytest.mark.parametrize("path", _SHIPPED_PROSE)
def test_shipped_prose_carries_no_em_or_en_dash(path: str) -> None:
    text = (REPO_ROOT / path).read_text(encoding="utf-8")

    assert [line for line in text.splitlines() if _EM_OR_EN_DASH.search(line)] == []


def test_no_string_in_the_package_source_carries_an_em_or_en_dash() -> None:
    sources = sorted((REPO_ROOT / "src" / "skaldr").rglob("*.py"))

    assert [hit for source in sources for hit in _string_literals_with_a_dash(source)] == []


def _uncommented_lines_with_a_dash(template: str) -> list[str]:
    text = _TEMPLATE_COMMENT.sub("", template)
    return [line.strip() for line in text.splitlines() if _EM_OR_EN_DASH.search(line)]


def test_no_template_or_stylesheet_text_carries_an_em_or_en_dash() -> None:
    package = REPO_ROOT / "src" / "skaldr"
    sources = [*sorted((package / "components").glob("*.j2")), package / "styles.css"]
    hits = {
        str(source.relative_to(REPO_ROOT)): _uncommented_lines_with_a_dash(source.read_text(encoding="utf-8"))
        for source in sources
    }

    assert {path: lines for path, lines in hits.items() if lines} == {}


@pytest.mark.parametrize(
    ("template", "hits"),
    [
        pytest.param("{# a \N{EM DASH} b #}<p>x</p>", [], id="jinja-comment"),
        pytest.param("<!-- a \N{EM DASH} b -->", [], id="html-comment"),
        pytest.param("/* a\n \N{EM DASH} b */ p{}", [], id="multi-line-css-comment"),
        pytest.param(
            '.x::before{content:"\N{EM DASH} "}', ['.x::before{content:"\N{EM DASH} "}'], id="css-text"
        ),
        pytest.param("<b>Legend \N{EN DASH} x</b>", ["<b>Legend \N{EN DASH} x</b>"], id="html-text"),
    ],
)
def test_the_template_guard_reads_text_and_skips_comments(template: str, hits: list[str]) -> None:
    assert _uncommented_lines_with_a_dash(template) == hits
