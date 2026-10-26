import pytest

from skaldr.errors import ReportError
from skaldr.models import Swimlane, parse_report
from tests.factories import make_report


def _swimlane(**overrides: object) -> dict[str, object]:
    block: dict[str, object] = {
        "type": "swimlane",
        "lanes": ["A", "B"],
        "columns": ["C1", "C2"],
        "steps": [
            {"lane": "A", "col": "C1", "n": "1", "label": "x"},
            {"lane": "B", "col": "C2", "n": "2", "label": "y"},
        ],
    }
    block.update(overrides)
    return block


def _swimlane_block(report: object) -> Swimlane:
    parsed = parse_report(report)
    block = parsed.blocks[0]
    assert isinstance(block, Swimlane)
    return block


def test_swimlane_step_lane_must_be_a_declared_lane() -> None:
    block = _swimlane(
        lanes=["A"], columns=["C1"], steps=[{"lane": "Ghost", "col": "C1", "n": "1", "label": "x"}]
    )
    with pytest.raises(ReportError, match=r"swimlane step lane 'Ghost' is not one of the declared lanes"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_col_must_be_a_declared_column() -> None:
    block = _swimlane(
        lanes=["A"], columns=["C1"], steps=[{"lane": "A", "col": "Ghost", "n": "1", "label": "x"}]
    )
    with pytest.raises(ReportError, match=r"swimlane step col 'Ghost' is not one of the declared columns"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_value_accepts_int_and_float_and_defaults_to_none() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "x", "value": 3},
            {"lane": "A", "col": "C2", "n": "2", "label": "y", "value": 0.5},
            {"lane": "A", "col": "C1", "n": "3", "label": "z"},
        ],
    )
    parsed = _swimlane_block(make_report(blocks=[block]))
    assert [step.value for step in parsed.steps] == [3, 0.5, None]


def test_swimlane_step_value_rejects_a_boolean() -> None:
    """`value` is a Number, so a bool (an int subclass pydantic would coerce) is rejected."""
    block = _swimlane(
        lanes=["A"], columns=["C1"], steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "value": True}]
    )
    with pytest.raises(ReportError, match=r"steps\.0\.value.*number, not a boolean"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_url_rejects_an_unsafe_scheme() -> None:
    """A step `url` is gated to http/https/mailto so a `javascript:` link can't reach the href."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "url": "javascript:alert(1)"}],
    )
    with pytest.raises(ReportError, match=r"steps\.0.*url must be an http://, https://, or mailto: link"):
        parse_report(make_report(blocks=[block]))


@pytest.mark.parametrize("bad_state", ["urgent", "normal", "low"])
def test_swimlane_step_state_rejects_an_unknown_value(bad_state: str) -> None:
    """Unknown states are rejected — including `normal` and `low`, the retired pre-progress-axis
    values, so the breaking vocabulary change can't be silently reverted."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "state": bad_state}],
    )
    with pytest.raises(ReportError, match=r"steps\.0\.state"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_id_must_be_a_safe_slug() -> None:
    """A step `id` is a safe slug (ASCII letters/digits/_/-) so `depends_on` can reference it cleanly."""
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "id": "bad id"}],
    )
    with pytest.raises(ReportError, match=r"steps\.0\.id"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_id_and_depends_on_are_retained() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "a", "id": "x"},
            {"lane": "A", "col": "C2", "n": "2", "label": "b", "id": "y", "depends_on": ["x"]},
        ],
    )
    parsed = _swimlane_block(make_report(blocks=[block]))
    assert [(step.id, step.depends_on) for step in parsed.steps] == [("x", []), ("y", ["x"])]


def test_swimlane_step_ids_must_be_unique() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2"],
        steps=[
            {"lane": "A", "col": "C1", "n": "1", "label": "x", "id": "dup"},
            {"lane": "A", "col": "C2", "n": "2", "label": "y", "id": "dup"},
        ],
    )
    with pytest.raises(ReportError, match=r"swimlane step ids must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_depends_on_must_reference_a_known_id() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "depends_on": ["ghost"]}],
    )
    with pytest.raises(ReportError, match=r"depends_on references unknown step id 'ghost'"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_cannot_depend_on_itself() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "id": "a", "depends_on": ["a"]}],
    )
    with pytest.raises(ReportError, match=r"'a' cannot depend on itself"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_lane_and_column_ids_decouple_reference_from_display() -> None:
    """A lane/column may carry an id (the reference key) distinct from its display name; a bare string
    is shorthand for name-as-key. Columns also carry an optional `sub` caption."""
    block = {
        "type": "swimlane",
        "lanes": [{"id": "eng", "name": "Engineering"}],
        "columns": ["S1", {"id": "s2", "name": "Sprint 2", "sub": "→ MVP demo"}],
        "steps": [
            {"lane": "eng", "col": "S1", "n": "1", "label": "a"},
            {"lane": "eng", "col": "s2", "n": "2", "label": "b"},
        ],
    }
    parsed = _swimlane_block(make_report(blocks=[block]))
    assert [(lane.key, lane.name) for lane in parsed.lanes] == [("eng", "Engineering")]
    assert [(col.key, col.name, col.sub) for col in parsed.columns] == [
        ("S1", "S1", None),  # bare string → key == name, no sub
        ("s2", "Sprint 2", "→ MVP demo"),
    ]


def test_swimlane_column_ids_must_be_unique() -> None:
    block = {
        "type": "swimlane",
        "lanes": ["A"],
        "columns": [{"id": "x", "name": "First"}, {"id": "x", "name": "Second"}],
        "steps": [{"lane": "A", "col": "x", "n": "1", "label": "a"}],
    }
    with pytest.raises(ReportError, match=r"swimlane columns must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_lane_id_must_be_a_safe_slug() -> None:
    block = {
        "type": "swimlane",
        "lanes": [{"id": "bad id", "name": "X"}],
        "columns": ["C1"],
        "steps": [{"lane": "bad id", "col": "C1", "n": "1", "label": "a"}],
    }
    with pytest.raises(ReportError, match=r"lanes\.0\.id"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_column_id_must_be_a_safe_slug() -> None:
    block = {
        "type": "swimlane",
        "lanes": ["A"],
        "columns": [{"id": "bad id", "name": "X"}],
        "steps": [{"lane": "A", "col": "bad id", "n": "1", "label": "a"}],
    }
    with pytest.raises(ReportError, match=r"columns\.0\.id"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_lane_ids_must_be_unique() -> None:
    block = {
        "type": "swimlane",
        "lanes": [{"id": "x", "name": "First"}, {"id": "x", "name": "Second"}],
        "columns": ["C1"],
        "steps": [{"lane": "x", "col": "C1", "n": "1", "label": "a"}],
    }
    with pytest.raises(ReportError, match=r"swimlane lanes must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_column_key_collides_across_string_and_object_forms() -> None:
    """A bare-string column's implicit key (its name) collides with another column's explicit id."""
    block = {
        "type": "swimlane",
        "lanes": ["A"],
        "columns": ["S1", {"id": "S1", "name": "Other"}],  # both resolve to key "S1"
        "steps": [{"lane": "A", "col": "S1", "n": "1", "label": "a"}],
    }
    with pytest.raises(ReportError, match=r"swimlane columns must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_col_references_the_key_not_the_display_name() -> None:
    """With an explicit id, a step must reference the id — the display name is not the key."""
    block = {
        "type": "swimlane",
        "lanes": ["A"],
        "columns": [{"id": "s1", "name": "Sprint 1"}],
        "steps": [{"lane": "A", "col": "Sprint 1", "n": "1", "label": "a"}],  # uses the name, not the id
    }
    with pytest.raises(ReportError, match=r"swimlane step col 'Sprint 1' is not one of the declared columns"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_lanes_must_be_unique() -> None:
    block = _swimlane(lanes=["A", "A"])
    with pytest.raises(ReportError, match=r"swimlane lanes must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_columns_must_be_unique() -> None:
    block = _swimlane(columns=["C1", "C1"])
    with pytest.raises(ReportError, match=r"swimlane columns must be unique"):
        parse_report(make_report(blocks=[block]))


@pytest.mark.parametrize("field", ["lane", "col", "n", "label"])
def test_swimlane_step_field_may_not_be_blank(field: str) -> None:
    step = {"lane": "A", "col": "C1", "n": "1", "label": "x", field: "  "}
    block = _swimlane(lanes=["A"], columns=["C1"], steps=[step])
    with pytest.raises(
        ReportError, match=rf"blocks\.0\.swimlane\.steps\.0\.{field}: String should match pattern '\\S'$"
    ):
        parse_report(make_report(blocks=[block]))


def test_swimlane_allows_at_most_eight_lanes() -> None:
    block = _swimlane(
        lanes=[f"L{i}" for i in range(9)],
        columns=["C1"],
        steps=[{"lane": "L0", "col": "C1", "n": "1", "label": "x"}],
    )
    with pytest.raises(ReportError, match=r"blocks\.0\.swimlane\.lanes.*at most 8"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_lane_with_no_steps_is_rejected() -> None:
    block = _swimlane(
        lanes=["A", "B"], columns=["C1"], steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x"}]
    )
    with pytest.raises(ReportError, match=r"swimlane lane 'B' has no steps"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_column_with_no_steps_is_rejected() -> None:
    block = _swimlane(
        lanes=["A"], columns=["C1", "C2"], steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x"}]
    )
    with pytest.raises(ReportError, match=r"swimlane column 'C2' has no steps"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_group_names_must_be_unique() -> None:
    block = _swimlane(
        groups=[
            {"name": "G", "color": "blue", "columns": ["C1"]},
            {"name": "G", "color": "amber", "columns": ["C2"]},
        ]
    )
    with pytest.raises(ReportError, match=r"swimlane group names must be unique"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_group_column_must_be_declared() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        groups=[{"name": "G", "color": "blue", "columns": ["Ghost"]}],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x"}],
    )
    with pytest.raises(ReportError, match=r"swimlane group 'G' references undeclared column\(s\): Ghost"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_group_columns_must_be_contiguous() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2", "C3"],
        groups=[{"name": "G", "color": "blue", "columns": ["C1", "C3"]}],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x"}],
    )
    with pytest.raises(ReportError, match=r"swimlane group 'G' columns must be contiguous in column order"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_group_must_be_declared() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        groups=[{"name": "G", "color": "blue", "columns": ["C1"]}],
        steps=[{"lane": "A", "col": "C1", "group": "Nope", "n": "1", "label": "x"}],
    )
    with pytest.raises(ReportError, match=r"swimlane step group 'Nope' is not a declared group"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_group_must_cover_its_column() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2"],
        groups=[{"name": "G", "color": "blue", "columns": ["C1"]}],
        steps=[
            {"lane": "A", "col": "C1", "group": "G", "n": "1", "label": "x"},
            {"lane": "A", "col": "C2", "group": "G", "n": "2", "label": "y"},
        ],
    )
    with pytest.raises(ReportError, match=r"swimlane step group 'G' does not cover column 'C2'"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_step_in_a_split_column_must_name_its_group() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        groups=[
            {"name": "G1", "color": "blue", "columns": ["C1"]},
            {"name": "G2", "color": "amber", "columns": ["C1"]},
        ],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x"}],
    )
    with pytest.raises(
        ReportError,
        match=r"swimlane step in column 'C1' must name a group: that column is split across 2 groups",
    ):
        parse_report(make_report(blocks=[block]))


def test_swimlane_group_with_no_steps_is_rejected() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        groups=[
            {"name": "G1", "color": "blue", "columns": ["C1"]},
            {"name": "G2", "color": "amber", "columns": ["C1"]},
        ],
        steps=[{"lane": "A", "col": "C1", "group": "G1", "n": "1", "label": "x"}],
    )
    with pytest.raises(ReportError, match=r"swimlane group 'G2' has no steps"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_interleaving_groups_are_rejected() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1", "C2", "C3"],
        groups=[
            {"name": "Wide", "color": "blue", "columns": ["C1", "C2", "C3"]},
            {"name": "Mid", "color": "amber", "columns": ["C2"]},
        ],
        steps=[
            {"lane": "A", "col": "C1", "group": "Wide", "n": "1", "label": "x"},
            {"lane": "A", "col": "C2", "group": "Mid", "n": "2", "label": "y"},
            {"lane": "A", "col": "C3", "group": "Wide", "n": "3", "label": "z"},
        ],
    )
    with pytest.raises(ReportError, match=r"swimlane group 'Wide' cannot be laid out contiguously"):
        parse_report(make_report(blocks=[block]))


def test_swimlane_without_groups_has_one_subcolumn_per_column() -> None:
    block = _swimlane_block(make_report(blocks=[_swimlane()]))

    assert block.groups == []
    assert block.subcolumns() == (("C1", None), ("C2", None))


def test_swimlane_orders_a_split_columns_subcolumns_by_span_then_declaration() -> None:
    block = _swimlane_block(
        make_report(
            blocks=[
                _swimlane(
                    lanes=["R"],
                    columns=["S1", "S2", "S3"],
                    groups=[
                        {"name": "MVP", "color": "blue", "columns": ["S1", "S2"]},
                        {"name": "Beta", "color": "amber", "columns": ["S2"]},
                        {"name": "GA", "color": "violet", "columns": ["S2", "S3"]},
                    ],
                    steps=[
                        {"lane": "R", "col": "S1", "n": "1", "label": "a"},
                        {"lane": "R", "col": "S2", "group": "Beta", "n": "2", "label": "b"},
                        {"lane": "R", "col": "S3", "n": "3", "label": "c"},
                    ],
                )
            ]
        )
    )

    assert block.subcolumns() == (
        ("S1", "MVP"),
        ("S2", "MVP"),
        ("S2", "Beta"),
        ("S2", "GA"),
        ("S3", "GA"),
    )


def test_swimlane_leaves_an_ungrouped_column_among_grouped_columns_untouched() -> None:
    block = _swimlane_block(
        make_report(
            blocks=[
                _swimlane(
                    lanes=["R"],
                    columns=["Early", "Mid", "Late"],
                    groups=[{"name": "Push", "color": "blue", "columns": ["Early", "Mid"]}],
                    steps=[
                        {"lane": "R", "col": "Early", "n": "1", "label": "a"},
                        {"lane": "R", "col": "Mid", "n": "2", "label": "b"},
                        {"lane": "R", "col": "Late", "n": "3", "label": "c"},
                    ],
                )
            ]
        )
    )

    assert block.subcolumns() == (("Early", "Push"), ("Mid", "Push"), ("Late", None))


def test_a_swimlane_step_url_that_is_malformed_is_refused() -> None:
    block = _swimlane(
        lanes=["A"],
        columns=["C1"],
        steps=[{"lane": "A", "col": "C1", "n": "1", "label": "x", "url": "https://"}],
    )

    with pytest.raises(ReportError, match=r"swimlane step url 'https://' is not a valid URL \(empty host\)"):
        parse_report(make_report(blocks=[block]))
