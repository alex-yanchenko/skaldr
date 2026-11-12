from collections.abc import Mapping

import pytest

from tests import node_page

SKIP_REASON = "the page scripts run under node"


@pytest.mark.parametrize(
    ("node", "environ", "skipped"),
    [
        pytest.param(None, {}, True, id="missing-and-local"),
        pytest.param(None, {"CI": ""}, True, id="missing-and-ci-empty"),
        pytest.param(None, {"CI": "true"}, False, id="missing-in-ci-so-the-tests-run-and-fail"),
        pytest.param("/usr/bin/node", {}, False, id="installed-and-local"),
        pytest.param("/usr/bin/node", {"CI": "true"}, False, id="installed-in-ci"),
    ],
)
def test_the_page_script_tests_are_skipped_only_when_node_is_missing_outside_ci(
    node: str | None, environ: Mapping[str, str], skipped: bool
) -> None:
    mark = node_page.node_requirement(node, environ).mark

    assert (mark.name, mark.args, mark.kwargs) == ("skipif", (skipped,), {"reason": SKIP_REASON})


def test_the_requires_node_mark_is_built_from_this_machine_and_its_environment() -> None:
    expected = node_page.node_requirement(node_page.NODE, node_page.os.environ).mark

    assert node_page.requires_node.mark == expected


def test_a_missing_node_fails_a_page_script_test_with_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(node_page, "NODE", None)

    with pytest.raises(pytest.fail.Exception) as failure:
        node_page.node_binary()

    assert str(failure.value) == "node is not installed, and the page script tests need it"


def test_an_installed_node_is_the_binary_the_page_scripts_run_under(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(node_page, "NODE", "/usr/bin/node")

    assert node_page.node_binary() == "/usr/bin/node"
