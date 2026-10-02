import re

import pytest

from skaldr.models import Report, package_text
from tests.conftest import REPO_ROOT

GUIDE = package_text("skill/GUIDE.md")
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")


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
