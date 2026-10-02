import ast
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

import pytest
import yaml

from skaldr.export import ExportTarget
from skaldr.models import AnyBlock, Report, package_text, parse_report
from skaldr.render import render_html
from tests.conftest import REPO_ROOT
from tests.factories.report_factory import make_report

GUIDE = package_text("skill/GUIDE.md")
SKILL = package_text("skill/SKILL.md")
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

_FENCE_OPENING = re.compile(r"(?P<quote>> ?)?(?P<indent> *)```yaml")

_SKELETON_OPENINGS = (
    "version: 1          # required, integer",
    "meta:",
    "badges:",
    "- type: cards            # a summary that can't go stale",
    "- type: grid",
    "columns:",
    '- { key: access, label: "Access", kind: badge, placement: cell, width: 1 }',
    "badges: !include shared/badges.yaml   # a shared vocabulary across several reports",
    "publish:",
)

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
        return self.text.splitlines()[0]


def _yaml_examples(guide: str) -> list[GuideExample]:
    examples: list[GuideExample] = []
    body: list[str] | None = None
    quoted = False
    start = 0
    for number, line in enumerate(guide.splitlines(), start=1):
        if body is None:
            opening = _FENCE_OPENING.fullmatch(line)
            if opening:
                body, quoted, start = [], opening["quote"] is not None, number
            continue
        content = re.sub(r"^> ?", "", line) if quoted else line
        if content.strip() == "```":
            examples.append(GuideExample(start, textwrap.dedent("\n".join(body))))
            body = None
        else:
            body.append(content)
    return examples


_EXAMPLES = _yaml_examples(GUIDE)
_BUILDABLE = [example for example in _EXAMPLES if example.opening not in _SKELETON_OPENINGS]


def _as_document(example: GuideExample) -> object:
    data: object = yaml.safe_load(example.text)
    if isinstance(data, list):
        return make_report(badges=_GUIDE_BADGES, blocks=data)
    return data


def _top_level_keys_named_in(text: str) -> set[str]:
    sentence = re.search(r"^Top level is (.+?)nothing else\.", text, re.MULTILINE | re.DOTALL)
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


def test_every_skeleton_the_guide_example_test_skips_is_still_in_the_guide() -> None:
    skipped = tuple(example.opening for example in _EXAMPLES if example.opening in _SKELETON_OPENINGS)

    assert skipped == _SKELETON_OPENINGS


@pytest.mark.parametrize(
    "example", [pytest.param(example, id=f"line-{example.line}") for example in _BUILDABLE]
)
def test_a_guide_example_builds_when_copied(example: GuideExample) -> None:
    html = render_html(parse_report(_as_document(example)))

    assert html.startswith("<!doctype html>")


def _every_block_type() -> set[str]:
    return {get_args(model.model_fields["type"].annotation)[0] for model in get_args(AnyBlock)}


def _readme_block_list(readme: str) -> str:
    paragraph = re.search(r"^\*\*Blocks:\*\*(.*?)\n\n", readme, re.MULTILINE | re.DOTALL)
    assert paragraph is not None
    return paragraph.group(1)


def test_the_readme_block_list_names_every_block_type() -> None:
    listed = _readme_block_list(README)

    assert {kind for kind in _every_block_type() if f"`{kind}`" not in listed} == set()


@pytest.mark.parametrize("text", [pytest.param(SKILL, id="skill"), pytest.param(README, id="readme")])
def test_the_skill_and_the_readme_name_both_export_targets(text: str) -> None:
    named = {target for target in get_args(ExportTarget) if f"--export {target}" in text}

    assert named == set(get_args(ExportTarget))


EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)
_EM_OR_EN_DASH = re.compile(f"[{EM_DASH}{EN_DASH}]")

_SHIPPED_PROSE = (
    "README.md",
    "AGENTS.md",
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
