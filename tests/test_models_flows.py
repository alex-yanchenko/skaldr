import pytest

from skaldr.errors import ReportError
from skaldr.models import Fan, Flow, FlowStep, parse_report
from tests.factories import make_report


def test_flow_arrow_parses_to_whole_model_with_defaults() -> None:
    block = {"type": "flow", "steps": [{"label": "Source"}, {"label": "Deliver", "tone": "success"}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == Flow(
        type="flow",
        style="arrow",
        loop=False,
        numbered=True,
        steps=[FlowStep(label="Source"), FlowStep(label="Deliver", tone="success")],
    )


def test_flow_requires_at_least_two_steps() -> None:
    block = {"type": "flow", "steps": [{"label": "solo"}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.flow\.steps.*at least 2"):
        parse_report(make_report(blocks=[block]))


def test_flow_step_label_must_not_be_blank() -> None:
    block = {"type": "flow", "steps": [{"label": "  "}, {"label": "B"}]}

    with pytest.raises(
        ReportError, match=r"blocks\.0\.flow\.steps\.0\.label: String should match pattern '\\S'$"
    ):
        parse_report(make_report(blocks=[block]))


def test_flow_unknown_style_is_rejected() -> None:
    block = {"type": "flow", "style": "zigzag", "steps": [{"label": "A"}, {"label": "B"}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.flow\.style"):
        parse_report(make_report(blocks=[block]))


def test_flow_unknown_field_is_rejected_with_path() -> None:
    block = {"type": "flow", "steps": [{"label": "A"}, {"label": "B"}], "oops": 1}

    with pytest.raises(ReportError, match=r"blocks\.0\.flow\.oops.*not permitted"):
        parse_report(make_report(blocks=[block]))


def test_status_list_unknown_state_is_rejected() -> None:
    block = {"type": "status_list", "items": [{"state": "in_progress", "text": "x"}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.status_list\.items\.0\.state"):
        parse_report(make_report(blocks=[block]))


def test_fan_parses_to_whole_model_with_default_direction_in() -> None:
    block = {"type": "fan", "hub": {"label": "H"}, "spokes": [{"label": "A"}, {"label": "B"}]}

    report = parse_report(make_report(blocks=[block]))

    assert report.blocks[0] == Fan(
        type="fan",
        hub=FlowStep(label="H"),
        spokes=[FlowStep(label="A"), FlowStep(label="B")],
        direction="in",
    )


def test_fan_requires_at_least_two_spokes() -> None:
    block = {"type": "fan", "hub": {"label": "H"}, "spokes": [{"label": "solo"}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.fan\.spokes.*at least 2"):
        parse_report(make_report(blocks=[block]))


def test_fan_requires_a_hub() -> None:
    block = {"type": "fan", "spokes": [{"label": "A"}, {"label": "B"}]}

    with pytest.raises(ReportError, match=r"blocks\.0\.fan\.hub"):
        parse_report(make_report(blocks=[block]))


def test_fan_unknown_direction_is_rejected() -> None:
    block = {
        "type": "fan",
        "direction": "sideways",
        "hub": {"label": "H"},
        "spokes": [{"label": "A"}, {"label": "B"}],
    }

    with pytest.raises(ReportError, match=r"blocks\.0\.fan\.direction"):
        parse_report(make_report(blocks=[block]))
