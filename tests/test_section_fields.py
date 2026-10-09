import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from skaldr import compute
from skaldr.errors import ReportError
from skaldr.export.inline import bold, plain
from skaldr.export.lower import lower_report
from skaldr.export.tree import Heading, ListEntry, ListNode, Paragraph, Toggle
from skaldr.models import Part, Report, Section, SectionFields, load_report, parse_report
from skaldr.render import render_html
from skaldr.richtext import AnchorLink, Plain
from tests.factories import make_report, make_section, markdown_of, notion_of, write_index_document

FULL_FIELDS: dict[str, Any] = {
    "status": "In Progress",
    "priority": "High",
    "assignee": "ada",
    "due": date(2026, 10, 15),
    "labels": ["onboarding", "bins"],
    "estimate": 3,
    "links": {"blocks": ["st3"]},
}


def fielded_report(fields: dict[str, Any], **section: Any) -> dict[str, Any]:
    return make_report(
        blocks=[
            make_section("st2", title="Widen the bin code", collapsed=False, fields=fields, **section),
            make_section("st3", title="Relabel the aisles", collapsed=False),
        ]
    )


def fields_of(report: Report, index: int = 0) -> SectionFields:
    section = report.blocks[index]
    assert isinstance(section, Section)
    assert section.fields is not None
    return section.fields


def test_known_keys_parse_to_typed_values() -> None:
    fields = fields_of(parse_report(fielded_report(FULL_FIELDS)))

    assert fields == SectionFields(
        status="In Progress",
        priority="High",
        assignee="ada",
        due=date(2026, 10, 15),
        labels=["onboarding", "bins"],
        estimate=3,
        links={"blocks": ["st3"]},
    )


def test_a_quoted_iso_date_parses_as_a_date() -> None:
    fields = fields_of(parse_report(fielded_report({"due": "2026-10-15"})))

    assert fields.due == date(2026, 10, 15)


def test_unknown_keys_are_kept_as_strings_numbers_and_lists() -> None:
    fields = fields_of(
        parse_report(fielded_report({"team": "Floor ops", "points": 2.5, "components": ["a", 4]}))
    )

    assert fields.model_extra == {"team": "Floor ops", "points": 2.5, "components": ["a", 4]}


def test_a_section_without_fields_has_none() -> None:
    report = parse_report(make_report(blocks=[make_section("st2")]))

    section = report.blocks[0]
    assert isinstance(section, Section)
    assert section.fields is None


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        pytest.param(
            {"due": "next week"},
            "invalid content data: blocks.0.section.fields.due: Value error, due must be an ISO date "
            "such as 2026-10-15, not 'next week'",
            id="due-not-a-date",
        ),
        pytest.param(
            {"estimate": True},
            "invalid content data: blocks.0.section.fields.estimate: Value error, must be a number, "
            "not a boolean",
            id="estimate-boolean",
        ),
        pytest.param(
            {"labels": []},
            "invalid content data: blocks.0.section.fields.labels: List should have at least 1 item "
            "after validation, not 0",
            id="empty-labels",
        ),
        pytest.param(
            {"status": " "},
            "invalid content data: blocks.0.section.fields.status: String should match pattern '\\S'",
            id="blank-status",
        ),
        pytest.param(
            {"links": {"blocks": []}},
            "invalid content data: blocks.0.section.fields.links.blocks: List should have at least 1 "
            "item after validation, not 0",
            id="empty-link-list",
        ),
        pytest.param(
            {"links": {"blocks": ["st9"]}},
            "invalid content data: Value error, section link 'blocks' names 'st9', which is not the id "
            "of any section, at blocks.0.section.fields.links.blocks.0",
            id="link-to-a-missing-section",
        ),
        pytest.param(
            {"team": {"name": "ops"}},
            "invalid content data: blocks.0.section.fields.team: Value error, an extra field must be a "
            "string, a number or a list of them, not a mapping",
            id="extra-mapping",
        ),
        pytest.param(
            {"team": True},
            "invalid content data: blocks.0.section.fields.team: Value error, an extra field must be a "
            "string, a number or a list of them, not a boolean",
            id="extra-boolean",
        ),
    ],
)
def test_a_bad_field_is_refused_with_its_path(fields: dict[str, Any], message: str) -> None:
    with pytest.raises(ReportError) as refused:
        parse_report(make_report(blocks=[make_section("st2", fields=fields)]))

    assert str(refused.value) == message


def test_a_link_may_target_a_section_declared_later_in_the_document() -> None:
    report = parse_report(
        fielded_report({"links": {"relates": ["st3"]}}),
    )

    assert fields_of(report).links == {"relates": ["st3"]}


def test_the_html_fact_strip_sits_at_the_top_of_the_section_body() -> None:
    html = render_html(parse_report(fielded_report(FULL_FIELDS)))

    assert (
        '<details class="section" id="st2" open><summary>Widen the bin code</summary>'
        '<div class="section-body"><div class="sfields">'
        '<span class="sf"><span class="k">Status</span><span class="chip blue">In Progress</span></span>'
        '<span class="sf"><span class="k">Priority</span><span class="chip amber">High</span></span>'
        '<span class="sf"><span class="k">Assignee</span><span class="person">ada</span></span>'
        '<span class="sf"><span class="k">Due</span><time datetime="2026-10-15">2026-10-15</time></span>'
        '<span class="sf"><span class="k">Labels</span><span class="chip slate">onboarding</span>'
        '<span class="chip slate">bins</span></span>'
        '<span class="sf"><span class="k">Estimate</span><span>3</span></span>'
        '<span class="sf"><span class="k">Blocks</span><a href="#st3">Relabel the aisles</a></span>'
        "</div>"
    ) in html


def test_the_html_shows_extra_fields_as_generic_chips() -> None:
    html = render_html(parse_report(fielded_report({"team": "Floor ops", "components": ["a", 4]})))

    assert (
        '<div class="sfields">'
        '<span class="sf"><span class="k">team</span><span class="chip slate">Floor ops</span></span>'
        '<span class="sf"><span class="k">components</span><span class="chip slate">a</span>'
        '<span class="chip slate">4</span></span>'
        "</div>"
    ) in html


def test_the_html_escapes_field_values() -> None:
    html = render_html(parse_report(fielded_report({"status": "<b>x</b>", "assignee": "a&b"})))

    assert (
        '<div class="sfields">'
        '<span class="sf"><span class="k">Status</span>'
        '<span class="chip blue">&lt;b&gt;x&lt;/b&gt;</span></span>'
        '<span class="sf"><span class="k">Assignee</span><span class="person">a&amp;b</span></span>'
        "</div>"
    ) in html


def test_a_section_without_fields_renders_no_fact_strip() -> None:
    html = render_html(parse_report(make_report(blocks=[make_section("st2")])))

    assert "sfields" not in html.split("</style>")[-1]


def test_the_lowered_section_opens_with_a_bulleted_fact_list() -> None:
    lowered = lower_report(parse_report(fielded_report(FULL_FIELDS))).body

    assert lowered[0] == Heading(
        2,
        (Plain("Widen the bin code"),),
        "st2",
    )
    assert lowered[1] == ListNode(
        "bullet",
        (
            ListEntry((*bold("Status"), Plain(": "), *plain("In Progress"))),
            ListEntry((*bold("Priority"), Plain(": "), *plain("High"))),
            ListEntry((*bold("Assignee"), Plain(": "), *plain("ada"))),
            ListEntry((*bold("Due"), Plain(": "), *plain("2026-10-15"))),
            ListEntry((*bold("Labels"), Plain(": "), *plain("onboarding, bins"))),
            ListEntry((*bold("Estimate"), Plain(": "), *plain("3"))),
            ListEntry(
                (
                    *bold("Blocks"),
                    Plain(": "),
                    AnchorLink(plain("Relabel the aisles"), "st3"),
                )
            ),
        ),
    )


def test_a_collapsed_section_keeps_the_fact_list_inside_its_toggle() -> None:
    report = make_report(
        blocks=[make_section("st2", title="Widen", fields={"status": "Done"}, collapsed=True)]
    )

    assert lower_report(parse_report(report)).body == (
        Toggle(
            (Plain("Widen"),),
            2,
            (
                ListNode("bullet", (ListEntry((*bold("Status"), Plain(": "), *plain("Done"))),)),
                Paragraph((Plain("x"),)),
            ),
            "st2",
        ),
    )


def test_the_github_markdown_lists_the_facts_under_the_section_heading() -> None:
    blocks = fielded_report(FULL_FIELDS)["blocks"]

    assert markdown_of(blocks) == (
        "## Widen the bin code\n"
        "\n"
        "- **Status**: In Progress\n"
        "- **Priority**: High\n"
        "- **Assignee**: ada\n"
        "- **Due**: 2026-10-15\n"
        "- **Labels**: onboarding, bins\n"
        "- **Estimate**: 3\n"
        "- **Blocks**: [Relabel the aisles](#relabel-the-aisles)\n"
        "\n"
        "x\n"
        "\n"
        "## Relabel the aisles\n"
        "\n"
        "x\n"
    )


def test_the_notion_markdown_lists_the_facts_under_the_section_heading() -> None:
    blocks = fielded_report({"status": "In Progress", "estimate": 2.5})["blocks"]

    assert notion_of(blocks) == (
        "## Widen the bin code\n- **Status**: In Progress\n- **Estimate**: 2.5\nx\n## Relabel the aisles\nx\n"
    )


def test_emit_json_carries_the_fields_with_the_date_as_text() -> None:
    dumped = parse_report(fielded_report({**FULL_FIELDS, "team": "Floor ops"})).model_dump(mode="json")

    section: dict[str, Any] = dumped["blocks"][0]
    assert section["fields"] == {
        "status": "In Progress",
        "priority": "High",
        "assignee": "ada",
        "due": "2026-10-15",
        "labels": ["onboarding", "bins"],
        "estimate": 3,
        "links": {"blocks": ["st3"]},
        "team": "Floor ops",
    }


def test_the_cli_emit_json_round_trips_the_fields(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from skaldr.cli import main

    data_path = tmp_path / "doc.yaml"
    data_path.write_text(
        "version: 1\n"
        "meta: {title: Count}\n"
        "blocks:\n"
        "  - type: section\n"
        "    id: st2\n"
        "    title: Widen\n"
        "    fields: {status: Open, due: 2026-10-15, labels: [bins]}\n"
        "    blocks: [{type: text, body: x}]\n",
        encoding="utf-8",
    )

    exit_code = main(["--emit-json", str(data_path)])

    section = json.loads(capsys.readouterr().out)["blocks"][0]
    assert (exit_code, section["fields"]) == (
        0,
        {
            "status": "Open",
            "priority": None,
            "assignee": None,
            "due": "2026-10-15",
            "labels": ["bins"],
            "estimate": None,
            "links": {},
        },
    )


NUMBER_FIELDS: dict[str, Any] = {
    "estimate": 1000,
    "year": 2026,
    "points": 1234.5,
    "whole": 3.0,
    "tags": [1500, "x"],
}


def numbered_blocks() -> list[dict[str, Any]]:
    return [make_section("st2", title="T", collapsed=False, fields=NUMBER_FIELDS)]


def test_the_html_shows_numbers_without_thousands_separators() -> None:
    html = render_html(parse_report(make_report(blocks=numbered_blocks())))

    assert (
        '<div class="sfields">'
        '<span class="sf"><span class="k">Estimate</span><span>1000</span></span>'
        '<span class="sf"><span class="k">year</span><span class="chip slate">2026</span></span>'
        '<span class="sf"><span class="k">points</span><span class="chip slate">1234.5</span></span>'
        '<span class="sf"><span class="k">whole</span><span class="chip slate">3</span></span>'
        '<span class="sf"><span class="k">tags</span><span class="chip slate">1500</span>'
        '<span class="chip slate">x</span></span>'
        "</div>"
    ) in html


def test_both_markdown_flavours_show_numbers_without_thousands_separators() -> None:
    expected_facts = (
        "- **Estimate**: 1000\n- **year**: 2026\n- **points**: 1234.5\n- **whole**: 3\n- **tags**: 1500, x\n"
    )

    assert (markdown_of(numbered_blocks()), notion_of(numbered_blocks())) == (
        f"## T\n\n{expected_facts}\nx\n",
        f"## T\n{expected_facts}x\n",
    )


HOSTILE_FIELDS: dict[str, Any] = {
    "status": "{color=red}",
    "priority": "__x__",
    "assignee": "<script>",
    "labels": ["[l](u)", "a|b"],
    "team": "*bold* `c`",
    "tags": ["x_y", 7],
}


def test_hostile_field_values_are_escaped_in_github_markdown() -> None:
    blocks = [make_section("st2", title="T", collapsed=False, fields=HOSTILE_FIELDS)]

    assert markdown_of(blocks) == (
        "## T\n"
        "\n"
        "- **Status**: {color=red}\n"
        "- **Priority**: \\_\\_x\\_\\_\n"
        "- **Assignee**: \\<script\\>\n"
        "- **Labels**: \\[l\\](u), a|b\n"
        "- **team**: \\*bold\\* \\`c\\`\n"
        "- **tags**: x\\_y, 7\n"
        "\n"
        "x\n"
    )


def test_hostile_field_values_are_escaped_in_notion_markdown() -> None:
    blocks = [make_section("st2", title="T", collapsed=False, fields=HOSTILE_FIELDS)]

    assert notion_of(blocks) == (
        "## T\n"
        "- **Status**: \\{color\\=red\\}\n"
        "- **Priority**: \\_\\_x\\_\\_\n"
        "- **Assignee**: \\<script\\>\n"
        "- **Labels**: \\[l\\](u), a\\|b\n"
        "- **team**: \\*bold\\* \\`c\\`\n"
        "- **tags**: x\\_y, 7\n"
        "x\n"
    )


def test_the_html_escapes_hostile_extras_and_labels() -> None:
    html = render_html(parse_report(fielded_report({"<script>": ["a|b", "{color=red}"]})))

    assert (
        '<div class="sfields"><span class="sf"><span class="k">&lt;script&gt;</span>'
        '<span class="chip slate">a|b</span><span class="chip slate">{color=red}</span></span></div>'
    ) in html


def test_a_link_type_label_keeps_the_rest_of_its_case() -> None:
    blocks = fielded_report({"links": {"QA review": ["st3"]}})["blocks"]

    assert markdown_of(blocks) == (
        "## Widen the bin code\n"
        "\n"
        "- **QA review**: [Relabel the aisles](#relabel-the-aisles)\n"
        "\n"
        "x\n"
        "\n"
        "## Relabel the aisles\n"
        "\n"
        "x\n"
    )


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        pytest.param(
            {"Status": "x"},
            "invalid content data: blocks.0.section.fields: Value error, 'Status' (an extra field) and "
            "'status' (a known field) would both show as 'Status'; rename one of them",
            id="extra-collides-with-a-known-field",
        ),
        pytest.param(
            {"Blocks": "x", "links": {"blocks": ["st2"]}},
            "invalid content data: blocks.0.section.fields: Value error, 'Blocks' (an extra field) and "
            "'blocks' (a link type) would both show as 'Blocks'; rename one of them",
            id="extra-collides-with-a-link-type",
        ),
        pytest.param(
            {"links": {"due": ["st2"]}},
            "invalid content data: blocks.0.section.fields: Value error, 'due' (a link type) and "
            "'due' (a known field) would both show as 'Due'; rename one of them",
            id="link-type-collides-with-a-known-field",
        ),
    ],
)
def test_a_label_shown_twice_is_refused(fields: dict[str, Any], message: str) -> None:
    with pytest.raises(ReportError) as refused:
        parse_report(make_report(blocks=[make_section("st2", fields=fields)]))

    assert str(refused.value) == message


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        pytest.param(" ", "an extra field must not be blank", id="blank-string"),
        pytest.param([], "an extra field list must not be empty", id="empty-list"),
        pytest.param(["a", " "], "an extra field must not be blank", id="blank-list-item"),
        pytest.param(float("nan"), "an extra field must be a finite number", id="nan"),
        pytest.param(float("inf"), "an extra field must be a finite number", id="inf"),
        pytest.param([1, float("-inf")], "an extra field must be a finite number", id="inf-in-a-list"),
        pytest.param(
            None, "an extra field must be a string, a number or a list of them, not null", id="null"
        ),
        pytest.param(
            [["a"]],
            "an extra field must be a string, a number or a list of them, not a list",
            id="nested-list",
        ),
    ],
)
def test_an_unusable_extra_is_refused_with_one_clean_message(value: Any, reason: str) -> None:
    with pytest.raises(ReportError) as refused:
        parse_report(make_report(blocks=[make_section("st2", fields={"team": value})]))

    assert str(refused.value) == f"invalid content data: blocks.0.section.fields.team: Value error, {reason}"


def test_a_link_inside_one_part_of_an_index_works(tmp_path: Path) -> None:
    part = make_report(
        meta={"title": "Plan"},
        blocks=[make_section("st2", fields={"links": {"blocks": ["st3"]}}), make_section("st3")],
    )
    index = write_index_document(tmp_path, {"plan.yaml": part})

    report = load_report(index)

    part_block = report.blocks[0]
    assert isinstance(part_block, Part)
    first = part_block.blocks[0]
    assert isinstance(first, Section)
    assert first.fields is not None
    assert first.fields.links == {"blocks": ["st3"]}


def test_a_link_cannot_reach_a_section_in_another_part_of_an_index(tmp_path: Path) -> None:
    first = make_report(
        meta={"title": "One"}, blocks=[make_section("st2", fields={"links": {"blocks": ["st3"]}})]
    )
    second = make_report(meta={"title": "Two"}, blocks=[make_section("st3")])
    index = write_index_document(tmp_path, {"one.yaml": first, "two.yaml": second})

    with pytest.raises(ReportError) as refused:
        load_report(index)

    assert str(refused.value) == (
        f"in part {(tmp_path / 'one.yaml').resolve()}: invalid content data: Value error, section link "
        "'blocks' names 'st3', which is not the id of any section, at "
        "blocks.0.section.fields.links.blocks.0"
    )


def test_lowering_finds_the_section_titles_once_for_every_fielded_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Report] = []
    real = compute.section_titles_by_id

    def counting(report: Report) -> dict[str, str]:
        calls.append(report)
        return real(report)

    monkeypatch.setattr(compute, "section_titles_by_id", counting)
    blocks = [make_section(f"st{n}", fields={"status": "Open"}) for n in range(3)]

    lower_report(parse_report(make_report(blocks=blocks)))

    assert len(calls) == 1
