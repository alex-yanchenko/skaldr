import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from skaldr.cli import main
from skaldr.compute import command_for, reader_variables, request_wire
from skaldr.errors import ReportError
from skaldr.models import Request, RequestFlow, parse_report, unresolvable_request_variables
from skaldr.render import render_html
from tests.factories import (
    make_command_request,
    make_flow,
    make_report,
    make_request,
    make_step,
    markdown_of,
    notion_of,
)

RECORDS_URL = "https://api.example.test/v1/records"
SHARED_COMMAND = (
    f"vault-run -- curl -s \"{RECORDS_URL}?id={{{{id}}}}&term={{{{term}}}}&seq={{{{seq}}}}\" | jq '.'\n"
)


def _shared_command_with(id_: str, term: str, seq: str) -> str:
    return f"vault-run -- curl -s \"{RECORDS_URL}?id={id_}&term={term}&seq={seq}\" | jq '.'"


VARIABLES = [{"name": "id"}, {"name": "term"}, {"name": "seq"}]
OK = {"status": 200, "body": "{}"}


def _command_request(**overrides: Any) -> dict[str, Any]:
    block: dict[str, Any] = make_command_request(
        command=SHARED_COMMAND,
        variables=VARIABLES,
        cases=[
            {
                "label": "Second term",
                "values": {"id": "A100", "term": "2", "seq": "1"},
                "tone": "warning",
                "response": {"body": "second"},
            },
            {
                "label": "Control",
                "values": {"id": "A100", "term": "1", "seq": "1"},
                "tone": "success",
                "response": {"body": "first"},
            },
        ],
    )
    block.update(overrides)
    return block


def _built_request(**overrides: Any) -> dict[str, Any]:
    block: dict[str, Any] = make_request(
        method="POST",
        url="https://api.example.test/v1/records/{{id}}",
        headers={"X-Term": "{{term}}"},
        body='{"seq":"{{seq}}"}',
        variables=VARIABLES,
        cases=[
            {"label": "Second term", "values": {"id": "A100", "term": "2", "seq": "1"}, "response": OK},
            {"label": "Control", "values": {"id": "A100", "term": "1", "seq": "1"}, "response": OK},
        ],
    )
    block.update(overrides)
    return block


def _parsed_request(block: dict[str, Any]) -> Request:
    parsed = parse_report(make_report(blocks=[block])).blocks[0]
    assert isinstance(parsed, Request)
    return parsed


def _parsed_flow(block: dict[str, Any]) -> RequestFlow:
    parsed = parse_report(make_report(blocks=[block])).blocks[0]
    assert isinstance(parsed, RequestFlow)
    return parsed


def test_a_shared_command_is_written_out_for_each_case_with_that_cases_values() -> None:
    block = _parsed_request(_command_request())

    assert [command_for(block, case) for case in block.cases] == [
        _shared_command_with("A100", "2", "1"),
        _shared_command_with("A100", "1", "1"),
    ]


def test_a_cases_own_command_takes_that_cases_values() -> None:
    own = "vault-run -- curl -s https://api.example.test/v1/other/{{id}}/{{term}}"
    cases = [
        {"label": "Own", "command": own, "values": {"id": "B7", "term": "9"}, "response": OK},
        {"label": "Shared", "values": {"id": "A100", "term": "1", "seq": "1"}, "response": OK},
    ]
    block = _parsed_request(_command_request(cases=cases, variables=VARIABLES))

    assert [command_for(block, case) for case in block.cases] == [
        "vault-run -- curl -s https://api.example.test/v1/other/B7/9",
        _shared_command_with("A100", "1", "1"),
    ]


def test_a_built_curl_fills_the_url_the_headers_and_the_body_from_the_cases_values() -> None:
    block = _parsed_request(_built_request())

    assert command_for(block, block.cases[0]) == (
        "curl -i -X POST \\\n"
        "  -H 'X-Term: 2' \\\n"
        '  --data \'{"seq":"1"}\' \\\n'
        "  https://api.example.test/v1/records/A100"
    )
    assert request_wire(block, block.cases[1]) == (
        'POST https://api.example.test/v1/records/A100\nX-Term: 1\n\n{"seq":"1"}'
    )


def test_a_value_with_a_quote_cannot_break_out_of_a_built_curl() -> None:
    hostile = {"id": "x'; echo owned; '", "term": "1", "seq": "1"}
    cases = [{"label": "Quote", "values": hostile, "response": OK}]
    block = _parsed_request(_built_request(cases=cases))

    assert command_for(block, block.cases[0]).splitlines()[-1] == (
        "  'https://api.example.test/v1/records/x'\"'\"'; echo owned; '\"'\"''"
    )


def test_a_variable_a_case_leaves_unbound_stays_a_blank_in_that_cases_command() -> None:
    cases = [
        {"label": "Partial", "values": {"id": "A100"}, "response": OK},
        {"label": "Whole", "values": {"id": "A100", "term": "1", "seq": "1"}, "response": OK},
    ]
    block = _parsed_request(_command_request(cases=cases))

    assert [command_for(block, case) for case in block.cases] == [
        _shared_command_with("A100", "{{term}}", "{{seq}}"),
        _shared_command_with("A100", "1", "1"),
    ]


def test_case_variable_with_value_still_fills_its_one_name() -> None:
    block = _parsed_request(
        make_request(
            url="https://api.example.test/{{resource}}",
            variables=[],
            case_variable="resource",
            cases=[
                {"label": "widgets", "response": OK},
                {"label": "admin", "value": "gadgets", "response": OK},
            ],
        )
    )

    assert [command_for(block, case).splitlines()[-1] for case in block.cases] == [
        "  https://api.example.test/widgets",
        "  https://api.example.test/gadgets",
    ]


def test_a_variable_every_case_binds_is_no_longer_a_field_the_reader_fills() -> None:
    cases = [
        {"label": "One", "values": {"id": "A100", "term": "2"}, "response": OK},
        {"label": "Two", "values": {"id": "A100", "term": "1"}, "response": OK},
    ]
    block = _parsed_request(_command_request(cases=cases))

    assert [variable.name for variable in reader_variables(block)] == ["seq"]


def test_a_variable_only_some_cases_bind_stays_a_field_for_the_cases_that_leave_it_open() -> None:
    cases = [
        {"label": "One", "values": {"id": "A100", "term": "2", "seq": "1"}, "response": OK},
        {"label": "Two", "values": {"id": "A100", "term": "1"}, "response": OK},
    ]
    block = _parsed_request(_command_request(cases=cases))

    assert [variable.name for variable in reader_variables(block)] == ["seq"]


def test_a_block_with_no_values_keeps_every_declared_variable_as_a_field() -> None:
    block = _parsed_request(_command_request(cases=[{"label": "Only", "response": OK}], variables=VARIABLES))

    assert [variable.name for variable in reader_variables(block)] == ["id", "term", "seq"]


def test_a_variable_no_case_binds_stays_a_field_even_where_every_case_overrides_the_request_text() -> None:
    cases = [{"label": "Only", "headers": {}, "response": OK}]
    block = _parsed_request(
        make_request(
            headers={"X-Term": "{{term}}"},
            url="https://api.example.test/{{id}}",
            variables=[{"name": "id"}, {"name": "term"}],
            cases=cases,
        )
    )

    assert [variable.name for variable in reader_variables(block)] == ["id", "term"]


def test_the_page_offers_a_field_only_for_what_the_cases_leave_open_and_writes_each_cases_values() -> None:
    cases = [
        {"label": "One", "values": {"id": "A100", "term": "2"}, "response": OK},
        {"label": "Two", "values": {"id": "A100", "term": "1"}, "response": OK},
    ]
    html = render_html(parse_report(make_report(blocks=[_command_request(cases=cases)])))

    assert re.findall(r'data-rq-var="([^"]+)"', html) == ["seq"]
    assert re.findall(r'data-rq-slot="([^"]+)"', html) == ["seq", "seq"]
    assert "records?id=A100&amp;term=2&amp;seq=" in html
    assert "records?id=A100&amp;term=1&amp;seq=" in html


def test_a_page_whose_cases_bind_every_variable_has_no_fields_and_no_slots() -> None:
    html = render_html(parse_report(make_report(blocks=[_command_request()])))

    assert re.findall(r'data-rq-var="([^"]+)"', html) == []
    assert re.findall(r'data-rq-slot="([^"]+)"', html) == []
    assert 'class="rq-vars"' not in html
    assert "records?id=A100&amp;term=2&amp;seq=1" in html
    assert "records?id=A100&amp;term=1&amp;seq=1" in html


def test_the_markdown_export_shows_each_cases_command_with_its_own_values() -> None:
    assert markdown_of([_command_request()]) == (
        "**Tier mappings on the partner API**\n\n"
        "**⚠️ Second term**\n\n"
        "```bash\n"
        "vault-run -- curl -s \"https://api.example.test/v1/records?id=A100&term=2&seq=1\" | jq '.'\n"
        "```\n\n"
        "**Recorded output**\n\n"
        "```\nsecond\n```\n\n"
        "**✅ Control**\n\n"
        "```bash\n"
        "vault-run -- curl -s \"https://api.example.test/v1/records?id=A100&term=1&seq=1\" | jq '.'\n"
        "```\n\n"
        "**Recorded output**\n\n"
        "```\nfirst\n```\n"
    )


def test_the_notion_export_shows_each_cases_command_with_its_own_values() -> None:
    second_term = _shared_command_with("A100", "2", "1")
    control = _shared_command_with("A100", "1", "1")

    assert notion_of([_command_request()]) == (
        "**Tier mappings on the partner API**\n"
        "<tabs>\n"
        '\t<tab icon="⚠️">\n'
        "\t\tSecond term\n"
        f"\t\t```bash\n\t\t{second_term}\n\t\t```\n"
        "\t\t**Recorded output**\n"
        "\t\t```plain text\n\t\tsecond\n\t\t```\n"
        "\t</tab>\n"
        '\t<tab icon="✅">\n'
        "\t\tControl\n"
        f"\t\t```bash\n\t\t{control}\n\t\t```\n"
        "\t\t**Recorded output**\n"
        "\t\t```plain text\n\t\tfirst\n\t\t```\n"
        "\t</tab>\n"
        "</tabs>\n"
    )


def test_the_markdown_export_lists_only_the_values_the_reader_still_supplies() -> None:
    cases = [
        {"label": "One", "values": {"id": "A100", "term": "2"}, "response": {"body": "x"}},
        {"label": "Two", "values": {"id": "A100", "term": "1"}, "response": {"body": "y"}},
    ]
    markdown = markdown_of([_command_request(cases=cases, command_note=None)])

    assert markdown.split("**One**")[0] == (
        "**Tier mappings on the partner API**\n\n**Values you supply**\n\n- `{{seq}}` seq: supply a value\n\n"
    )


def test_a_flow_step_fills_its_own_cases_and_the_capture_still_feeds_the_next_step() -> None:
    first = make_step(
        url="https://api.example.test/{{id}}/{{term}}",
        captures=[{"name": "token", "source": "body"}],
        cases=[{"label": "one", "values": {"id": "A100", "term": "2"}, "response": OK}],
    )
    second = make_step(
        url="https://api.example.test/{{id}}/{{term}}",
        headers={"Authorization": "Bearer {{token}}"},
        cases=[
            {"label": "Second term", "values": {"id": "A100", "term": "2"}, "response": OK},
            {"label": "Control", "values": {"id": "A100", "term": "1"}, "response": OK},
        ],
    )
    flow = _parsed_flow(make_flow(variables=[{"name": "id"}, {"name": "term"}], steps=[first, second]))

    assert [command_for(flow.steps[1], case) for case in flow.steps[1].cases] == [
        "curl -i -X GET \\\n  -H 'Authorization: Bearer {{token}}' \\\n  https://api.example.test/A100/2",
        "curl -i -X GET \\\n  -H 'Authorization: Bearer {{token}}' \\\n  https://api.example.test/A100/1",
    ]
    assert reader_variables(flow) == []
    assert unresolvable_request_variables([flow]) == set()


def test_a_flow_keeps_a_variable_as_a_field_when_a_step_leaves_it_open() -> None:
    first = make_step(
        url="https://api.example.test/{{id}}",
        cases=[{"label": "one", "values": {"id": "A100"}, "response": OK}],
    )
    second = make_step(url="https://api.example.test/{{id}}/more")
    flow = _parsed_flow(make_flow(variables=[{"name": "id"}], steps=[first, second]))

    assert [variable.name for variable in reader_variables(flow)] == ["id"]


def test_a_flow_whose_cases_bind_every_variable_renders_only_the_fields_its_captures_produce() -> None:
    step = make_step(
        url="https://api.example.test/{{id}}",
        captures=[{"name": "token", "source": "body"}],
        cases=[{"label": "one", "values": {"id": "A100"}, "response": OK}],
    )
    follow = make_step(
        url="https://api.example.test/{{id}}/more",
        headers={"Authorization": "Bearer {{token}}"},
        cases=[{"label": "one", "values": {"id": "A100"}, "response": OK}],
    )
    html = render_html(
        parse_report(make_report(blocks=[make_flow(variables=[{"name": "id"}], steps=[step, follow])]))
    )

    assert re.findall(r'data-rq-var="([^"]+)"', html) == []
    assert re.findall(r'<input [^>]*data-rq-produced="([^"]+)"', html) == ["token"]


def test_strict_still_fails_an_undeclared_name_in_a_block_whose_cases_bind_values() -> None:
    block = _command_request(command=SHARED_COMMAND.replace("{{seq}}", "{{sequence}}"))
    block["cases"] = [
        {"label": "One", "values": {"id": "A100", "term": "2"}, "response": OK},
    ]
    block["variables"] = [{"name": "id"}, {"name": "term"}]

    assert unresolvable_request_variables(parse_report(make_report(blocks=[block])).blocks) == {"sequence"}


def test_emit_json_carries_each_cases_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "report.yaml"
    path.write_text(yaml.safe_dump(make_report(blocks=[_command_request()])), encoding="utf-8")

    exit_code = main(["--emit-json", str(path)])

    cases = json.loads(capsys.readouterr().out)["blocks"][0]["cases"]
    assert exit_code == 0
    assert [(case["label"], case["value"], case["values"]) for case in cases] == [
        ("Second term", None, {"id": "A100", "term": "2", "seq": "1"}),
        ("Control", None, {"id": "A100", "term": "1", "seq": "1"}),
    ]


def _rejected(block: dict[str, Any]) -> str:
    with pytest.raises(ReportError) as refusal:
        parse_report(make_report(blocks=[block]))
    return str(refusal.value)


def test_a_case_setting_value_and_values_is_rejected_naming_the_case() -> None:
    cases = [{"label": "Second term", "value": "2", "values": {"id": "A100"}, "response": OK}]

    assert (
        "case 'Second term' sets value and values together: value fills the case_variable and values "
        "fills declared variables, so give the case one of them"
    ) in _rejected(_command_request(cases=cases))


def test_values_on_a_request_with_a_case_variable_is_rejected_naming_the_case() -> None:
    cases = [{"label": "Second term", "values": {"id": "A100"}, "response": OK}]
    block = _command_request(cases=cases, case_variable="term", variables=[{"name": "id"}, {"name": "seq"}])

    assert (
        "case 'Second term' sets values on a request that declares case_variable `term`: values and "
        "case_variable are two ways to fill a case, so use one"
    ) in _rejected(block)


def test_a_values_key_that_is_not_a_declared_variable_is_rejected_naming_the_case_and_key() -> None:
    cases = [{"label": "Second term", "values": {"id": "A100", "colour": "red"}, "response": OK}]

    assert (
        "case 'Second term' sets `colour` under values, but the request declares no variable named `colour`"
    ) in _rejected(_command_request(cases=cases))


def test_a_values_key_that_names_a_capture_is_rejected_in_a_flow_step() -> None:
    second = make_step(
        headers={"Authorization": "Bearer {{token}}"},
        cases=[{"label": "Control", "values": {"token": "abc"}, "response": OK}],
    )
    flow = make_flow(steps=[make_step(captures=[{"name": "token", "source": "body"}]), second])

    assert (
        "case 'Control' sets `token` under values, but the flow declares no variable named `token`"
    ) in _rejected(flow)


def test_a_flow_step_case_setting_value_and_values_is_rejected_naming_the_case() -> None:
    step = make_step(
        url="https://api.example.test/{{id}}",
        cases=[{"label": "Control", "value": "x", "values": {"id": "A100"}, "response": OK}],
    )

    assert (
        "case 'Control' sets value and values together: value fills the case_variable and values "
        "fills declared variables, so give the case one of them"
    ) in _rejected(make_flow(variables=[{"name": "id"}], steps=[step, make_step(url="https://x/{{id}}")]))


def test_a_flow_step_values_with_a_case_variable_is_rejected_naming_the_case() -> None:
    step = make_step(
        url="https://api.example.test/{{id}}/{{term}}",
        case_variable="term",
        cases=[{"label": "Control", "values": {"id": "A100"}, "response": OK}],
    )

    assert (
        "case 'Control' sets values on a request that declares case_variable `term`: values and "
        "case_variable are two ways to fill a case, so use one"
    ) in _rejected(make_flow(variables=[{"name": "id"}], steps=[step, make_step(url="https://x/{{id}}")]))


def test_an_empty_values_map_is_rejected() -> None:
    cases = [{"label": "Second term", "values": {}, "response": OK}]

    assert "should have at least 1 item" in _rejected(_command_request(cases=cases))


def test_a_secret_variable_cannot_be_bound_through_values() -> None:
    variables = [{"name": "id", "secret": True}, {"name": "term"}, {"name": "seq"}]

    assert (
        "case 'Second term' sets `id` under values, but `id` is a secret variable the reader supplies"
    ) in _rejected(_command_request(variables=variables))


def test_a_secret_variable_cannot_be_bound_through_values_in_a_flow_step() -> None:
    step = make_step(
        url="https://api.example.test/{{id}}",
        cases=[{"label": "Control", "values": {"id": "A100"}, "response": OK}],
    )

    assert (
        "case 'Control' sets `id` under values, but `id` is a secret variable the reader supplies"
    ) in _rejected(make_flow(variables=[{"name": "id", "secret": True}], steps=[step, step]))


def test_a_values_key_the_cases_own_command_never_uses_is_rejected() -> None:
    cases = [
        {
            "label": "Own",
            "command": "vault-run -- curl -s https://api.example.test/v1/other/{{id}}",
            "values": {"id": "B7", "term": "9"},
            "response": OK,
        }
    ]

    assert "case 'Own' sets `term` under values, but nothing it sends uses `{{term}}`" in _rejected(
        _command_request(cases=cases)
    )


def test_a_values_key_a_cases_replaced_headers_no_longer_carry_is_rejected() -> None:
    cases = [
        {"label": "Bare", "headers": {}, "values": {"id": "A100", "term": "2", "seq": "1"}, "response": OK}
    ]

    assert "case 'Bare' sets `term` under values, but nothing it sends uses `{{term}}`" in _rejected(
        _built_request(cases=cases)
    )


def test_a_value_carrying_a_token_is_inserted_as_written_and_the_token_stays_a_reader_slot() -> None:
    block = _command_request(
        command="fetch {{id}} {{term}}",
        variables=[{"name": "id"}, {"name": "term"}],
        cases=[{"label": "Nested", "values": {"id": "{{term}}"}, "response": OK}],
    )
    parsed = _parsed_request(block)
    html = render_html(parse_report(make_report(blocks=[block])))

    assert command_for(parsed, parsed.cases[0]) == "fetch {{term}} {{term}}"
    assert re.findall(r'data-rq-slot="([^"]+)"', html) == ["term", "term"]


def test_a_flow_with_no_reader_fields_and_no_captures_renders_no_fields_block() -> None:
    step = make_step(
        url="https://api.example.test/{{id}}",
        cases=[{"label": "one", "values": {"id": "A100"}, "response": OK}],
    )
    html = render_html(
        parse_report(make_report(blocks=[make_flow(variables=[{"name": "id"}], steps=[step, step])]))
    )

    assert 'class="rq-vars"' not in html
    assert "https://api.example.test/A100" in html


def test_a_flow_step_case_layers_headers_and_binds_values_together() -> None:
    step = make_step(
        url="https://api.example.test/{{id}}",
        cases=[
            {
                "label": "Second term",
                "headers_add": {"X-Term": "{{term}}"},
                "values": {"id": "A100", "term": "2"},
                "response": OK,
            }
        ],
    )
    flow = _parsed_flow(make_flow(variables=[{"name": "id"}, {"name": "term"}], steps=[step, step]))

    assert command_for(flow.steps[0], flow.steps[0].cases[0]) == (
        "curl -i -X GET \\\n  -H 'X-Term: 2' \\\n  https://api.example.test/A100"
    )


def test_a_blank_value_is_rejected() -> None:
    cases = [{"label": "Second term", "values": {"id": "  "}, "response": OK}]

    assert "blocks.0.request.cases.0.values.id: String should match pattern '\\S'" in _rejected(
        _command_request(cases=cases)
    )
