import tomllib
from typing import Any

import yaml

from tests.conftest import REPO_ROOT

COVERED_RUN = "uv run coverage run -m pytest"
COVERAGE_REPORT = "uv run coverage report"


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _test_job_commands() -> list[str]:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    return [step["run"] for step in workflow["jobs"]["test"]["steps"] if "run" in step]


def test_coverage_measures_branches_of_the_skaldr_package_and_fails_under_97_percent() -> None:
    coverage = _pyproject()["tool"]["coverage"]

    assert coverage == {
        "run": {"branch": True, "source": ["skaldr"]},
        "report": {"fail_under": 97},
    }


def test_coverage_is_a_locked_dev_dependency() -> None:
    dev = _pyproject()["dependency-groups"]["dev"]

    assert [entry for entry in dev if entry.startswith("coverage")] != []


def test_the_ci_test_job_runs_the_suite_under_coverage_and_then_checks_the_gate() -> None:
    commands = _test_job_commands()

    assert [command for command in commands if "coverage" in command] == [COVERED_RUN, COVERAGE_REPORT]
    assert commands.index(COVERED_RUN) + 1 == commands.index(COVERAGE_REPORT)


def test_the_ci_test_job_no_longer_runs_plain_pytest() -> None:
    assert "uv run pytest" not in _test_job_commands()
