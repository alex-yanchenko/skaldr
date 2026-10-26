from typing import Any

import pytest

from skaldr import compute
from skaldr.errors import ReportError
from skaldr.models import Panel, Request, RequestFlow, Section, parse_report
from tests.factories import (
    make_command_request,
    make_flow,
    make_query_request,
    make_report,
    make_request,
    make_step,
    make_toggle,
    parsed_request,
)


def test_two_requests_sharing_a_label_are_refused_when_one_sits_in_a_toggle() -> None:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[make_request(), make_toggle(make_request())]))

    assert str(raised.value) == (
        "invalid content data: Value error, request block label(s) used more than once: "
        "['Read an endpoint'], at blocks.0.request, blocks.1.toggle.blocks.0.request; request labels must "
        "be unique, because a label keys what a reader's fields are remembered under while their tab is "
        "open: give one of them an `id`"
    )


def test_a_request_repeating_several_case_labels_names_each_once_in_sorted_order() -> None:
    labels = ("b", "a", "b", "c", "a")
    cases = [{"label": label, "response": {"status": 200, "body": "[]"}} for label in labels]

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[make_request(cases=cases)]))

    assert str(raised.value) == (
        "invalid content data: blocks.0.request: Value error, request repeats a case label: a, b"
    )


def _request(**overrides: Any) -> dict[str, Any]:
    """The shared request with a case axis, which is the shape most of these validators need."""
    defaults: dict[str, Any] = {
        "url": "https://{{host}}/{{resource}}",
        "case_variable": "resource",
        "cases": [{"label": "widgets", "response": {"status": 200, "body": "[]"}}],
    }
    return make_request(**{**defaults, **overrides})


def test_a_request_declaring_a_variable_twice_is_rejected() -> None:
    variables = [{"name": "host", "example": "a"}, {"name": "host", "example": "b"}]
    with pytest.raises(ReportError, match=r"declares a variable twice: host"):
        parse_report(make_report(blocks=[_request(variables=variables)]))


def test_a_case_variable_that_is_also_a_declared_variable_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"both the case_variable and a declared variable"):
        parse_report(make_report(blocks=[_request(case_variable="host", url="https://x/{{host}}")]))


def test_a_request_repeating_a_case_label_is_rejected() -> None:
    cases = [
        {"label": "widgets", "response": {"body": "[]"}},
        {"label": "widgets", "response": {"body": "[]"}},
    ]
    with pytest.raises(ReportError, match=r"repeats a case label: widgets"):
        parse_report(make_report(blocks=[_request(cases=cases)]))


def test_a_case_value_without_a_case_variable_is_rejected() -> None:
    block = _request(
        url="https://{{host}}/widgets", cases=[{"label": "a", "value": "b", "response": {"body": "{}"}}]
    )
    del block["case_variable"]
    with pytest.raises(ReportError, match=r"sets a value but the request declares no case_variable"):
        parse_report(make_report(blocks=[block]))


def test_a_variable_that_is_never_interpolated_is_rejected() -> None:
    variables = [{"name": "host", "example": "a"}, {"name": "unused", "example": "b"}]
    with pytest.raises(ReportError, match=r"declares unused but never uses it"):
        parse_report(make_report(blocks=[_request(variables=variables)]))


@pytest.mark.parametrize("field", ["headers", "headers_add"])
@pytest.mark.parametrize(
    ("headers", "message"),
    [
        pytest.param({"": "x"}, r"request case header name must not be blank", id="blank-name"),
        pytest.param(
            {"X-Trace": "   "},
            r"request case header `X-Trace` must not have a blank value",
            id="blank-value",
        ),
        pytest.param(
            {"X-Trace": "a", "x-trace": "b"},
            r"differ only in case",
            id="case-variant-names",
        ),
    ],
)
def test_a_case_header_is_held_to_the_same_shape_as_the_requests(
    field: str, headers: dict[str, str], message: str
) -> None:
    """A case names its headers either way it sets them, and both reach the command a reader copies.
    A blank name renders a `: value` line the server rejects."""
    case = {"label": "one", field: headers, "response": {"status": 200, "body": "[]"}}
    with pytest.raises(ReportError, match=message):
        parse_report(make_report(blocks=[_request(cases=[case], case_variable=None)]))


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        pytest.param({"": "x"}, r"request header name must not be blank", id="blank-name"),
        pytest.param(
            {"Accept": " "}, r"request header `Accept` must not have a blank value", id="blank-value"
        ),
        pytest.param({"Accept": "a", "accept": "b"}, r"differ only in case", id="case-variant-names"),
    ],
)
def test_a_request_header_must_carry_a_name_and_a_value(headers: dict[str, str], message: str) -> None:
    with pytest.raises(ReportError, match=message):
        parse_report(make_report(blocks=[_request(headers=headers)]))


def test_a_boolean_status_is_rejected_rather_than_coerced_to_one() -> None:
    with pytest.raises(ReportError, match=r"must be a number, not a boolean"):
        parse_report(
            make_report(blocks=[_request(cases=[{"label": "a", "response": {"status": True, "body": "{}"}}])])
        )


def test_a_response_header_may_repeat() -> None:
    case = {
        "label": "widgets",
        "response": {"status": 200, "headers": {"set-cookie": ["a=1", "b=2"]}, "body": "[]"},
    }

    block = parse_report(make_report(blocks=[_request(cases=[case])])).blocks[0]
    assert isinstance(block, Request)

    assert block.cases[0].response.headers == {"set-cookie": ["a=1", "b=2"]}


def test_a_request_is_refused_inside_a_grid_cell_because_the_column_is_too_narrow() -> None:
    grid = {"type": "grid", "cells": [{"span": 2, "blocks": [_request()]}]}

    with pytest.raises(ReportError, match=r"blocks\.0"):
        parse_report(make_report(blocks=[grid]))


def test_a_request_is_accepted_inside_a_section() -> None:
    section = {"type": "section", "title": "Evidence", "blocks": [_request()]}

    report = parse_report(make_report(blocks=[section]))
    outer = report.blocks[0]
    assert isinstance(outer, Section)

    assert isinstance(outer.blocks[0], Request)


def test_a_valid_flow_parses() -> None:
    block = parse_report(make_report(blocks=[make_flow()])).blocks[0]

    assert isinstance(block, RequestFlow)
    assert block.produced_by(0) == set()
    assert block.produced_by(1) == {"token"}


def test_a_flow_declaring_a_variable_twice_is_rejected() -> None:
    variables = [{"name": "host", "example": "a"}, {"name": "host", "example": "b"}]
    with pytest.raises(ReportError, match=r"flow declares a variable twice: host"):
        parse_report(make_report(blocks=[make_flow(variables=variables)]))


def test_a_captured_name_that_is_also_a_declared_variable_is_rejected() -> None:
    variables = [{"name": "host", "example": "a"}, {"name": "token", "example": "b"}]
    with pytest.raises(ReportError, match=r"token is both captured and declared"):
        parse_report(make_report(blocks=[make_flow(variables=variables)]))


def test_two_steps_capturing_the_same_name_are_rejected() -> None:
    steps = [
        make_step(captures=[{"name": "token", "source": "body"}]),
        make_step(url="https://{{host}}/b?t={{token}}", captures=[{"name": "token", "source": "body"}]),
    ]
    with pytest.raises(ReportError, match=r"two steps capture the same name: token"):
        parse_report(make_report(blocks=[make_flow(steps=steps)]))


def test_a_step_using_a_capture_before_it_is_produced_is_rejected() -> None:
    """The ordering rule the whole block rests on. Without it a flow validates while a step reads a
    value that does not exist when the reader reaches it, and the script aborts under `set -u`."""
    steps = [
        make_step(url="https://{{host}}/a?t={{token}}"),
        make_step(url="https://{{host}}/b", captures=[{"name": "token", "source": "body"}]),
    ]
    with pytest.raises(ReportError, match=r"step 1 uses token before the step that captures it has run"):
        parse_report(make_report(blocks=[make_flow(steps=steps)]))


def test_a_step_reaching_forward_through_headers_add_is_rejected_too() -> None:
    """A case's `headers_add` is interpolated exactly like every other header, so the ordering rule
    reaches it: a step may only name a value some earlier step has already captured."""
    steps = [
        make_step(
            cases=[
                {
                    "label": "one",
                    "headers_add": {"X-Later": "{{token}}"},
                    "response": {"status": 200, "body": "{}"},
                }
            ]
        ),
        make_step(url="https://{{host}}/b", captures=[{"name": "token", "source": "body"}]),
    ]
    with pytest.raises(ReportError, match=r"step 1 uses token before the step that captures it has run"):
        parse_report(make_report(blocks=[make_flow(steps=steps)]))


def test_a_step_may_not_use_the_name_it_captures_itself() -> None:
    steps = [
        make_step(url="https://{{host}}/a?t={{token}}", captures=[{"name": "token", "source": "body"}]),
        make_step(url="https://{{host}}/b"),
    ]
    with pytest.raises(ReportError, match=r"step 1 uses token before the step that captures it has run"):
        parse_report(make_report(blocks=[make_flow(steps=steps)]))


def test_a_flow_name_no_step_uses_is_rejected() -> None:
    variables = [{"name": "host", "example": "a"}, {"name": "spare", "example": "b"}]
    with pytest.raises(ReportError, match=r"flow declares or captures spare but no step uses it"):
        parse_report(make_report(blocks=[make_flow(variables=variables)]))


def test_one_step_capturing_the_same_name_twice_is_rejected() -> None:
    captures = [{"name": "token", "source": "body"}, {"name": "token", "json_path": "$.t"}]
    steps = [make_step(captures=captures), make_step(url="https://{{host}}/b?t={{token}}")]
    with pytest.raises(ReportError, match=r"step captures the same name twice: token"):
        parse_report(make_report(blocks=[make_flow(steps=steps)]))


@pytest.mark.parametrize(
    "capture",
    [{"name": "token"}, {"name": "token", "source": "body", "json_path": "$.t"}],
    ids=["neither", "both"],
)
def test_a_capture_takes_exactly_one_of_source_or_json_path(capture: dict[str, Any]) -> None:
    steps = [make_step(captures=[capture]), make_step(url="https://{{host}}/b?t={{token}}")]
    with pytest.raises(ReportError, match=r"takes `source: body` or a `json_path`, exactly one"):
        parse_report(make_report(blocks=[make_flow(steps=steps)]))


def test_a_step_that_captures_may_record_only_one_case() -> None:
    """A capture is the value later steps read, so the step that produces it records the one call that
    produced it. Two cases would leave which of them the reader's captured value came from unsaid."""
    cases = [
        {"label": "ok", "response": {"status": 200, "body": "{}"}},
        {"label": "denied", "response": {"status": 401, "body": "{}"}},
    ]
    steps = [
        make_step(captures=[{"name": "token", "source": "body"}], cases=cases),
        make_step(url="https://{{host}}/b?t={{token}}"),
    ]
    with pytest.raises(ReportError, match=r"captures a value and records 2 cases"):
        parse_report(make_report(blocks=[make_flow(steps=steps)]))


@pytest.mark.parametrize(
    "path", ["$.items[0].id", "$.", "$token", "$.a..b"], ids=["array-index", "bare", "no-dot", "double-dot"]
)
def test_a_json_path_the_page_cannot_resolve_is_rejected(path: str) -> None:
    """The browser resolver splits on dots and looks up object keys. A path it cannot walk would fill
    the field with nothing and never say why, so the build refuses it instead."""
    steps = [
        make_step(captures=[{"name": "token", "json_path": path}]),
        make_step(url="https://{{host}}/b?t={{token}}"),
    ]
    with pytest.raises(ReportError, match=r"json_path"):
        parse_report(make_report(blocks=[make_flow(steps=steps)]))


def test_a_flow_of_one_step_is_rejected_because_that_is_a_request() -> None:
    with pytest.raises(ReportError, match=r"steps.*at least 2"):
        parse_report(make_report(blocks=[make_flow(steps=[make_step()])]))


def test_a_flow_step_is_validated_by_the_core_every_request_shares() -> None:
    """`RequestStep` reaches `_core_shape` through the extracted base rather than its own validator, so
    a step's cases are checked exactly as a standalone request's are."""
    duplicated = [
        {"label": "same", "response": {"status": 200, "body": "{}"}},
        {"label": "same", "response": {"status": 404, "body": "{}"}},
    ]
    steps = [
        make_step(captures=[{"name": "token", "source": "body"}], cases=duplicated),
        make_step(url="https://{{host}}/b?t={{token}}"),
    ]

    with pytest.raises(ReportError, match=r"request repeats a case label: same"):
        parse_report(make_report(blocks=[make_flow(steps=steps)]))


def test_a_secret_is_written_into_the_command_so_it_runs_as_copied() -> None:
    """A secret is a reader's field like any other once typed: the command carries the value, so one
    copy and one paste runs it."""
    block = parse_report(
        make_report(
            blocks=[
                _request(
                    headers={"Authorization": "Bearer {{key}}"},
                    variables=[
                        {"name": "host", "example": "api.example.com"},
                        {"name": "key", "secret": True},
                    ],
                )
            ]
        )
    ).blocks[0]
    assert isinstance(block, Request)

    assert "{{key}}" in compute.command_for(block, block.cases[0])
    assert "$KEY" not in compute.command_for(block, block.cases[0])


def test_two_request_blocks_sharing_a_label_are_rejected() -> None:
    """The label keys what a reader's fields are remembered under. Two blocks sharing it would share
    the values, so typing a host into one restores it into the other."""
    with pytest.raises(ReportError, match=r"request block label\(s\) used more than once"):
        parse_report(make_report(blocks=[_request(), _request()]))


def test_an_id_separates_two_request_blocks_that_share_a_label() -> None:
    report = parse_report(make_report(blocks=[_request(), _request(id="staging")]))
    second = report.blocks[1]
    assert isinstance(second, Request)

    assert second.id == "staging"


def test_a_request_and_a_flow_sharing_a_label_are_rejected() -> None:
    flow = make_flow(label="Read an endpoint")
    with pytest.raises(ReportError, match=r"request block label\(s\) used more than once"):
        parse_report(make_report(blocks=[_request(), flow]))


def test_a_capture_name_differing_only_in_case_is_its_own_name() -> None:
    """A captured name is a form field and a `{{token}}` the page substitutes, nothing more, so two
    names a shell would have flattened together stay distinct."""
    flow = make_flow(
        variables=[{"name": "host", "example": "a"}],
        steps=[
            make_step(captures=[{"name": "access-token", "source": "body"}]),
            make_step(
                url="https://{{host}}/b?a={{access-token}}",
                captures=[{"name": "ACCESS_TOKEN", "json_path": "$.t"}],
            ),
            make_step(url="https://{{host}}/c?x={{ACCESS_TOKEN}}"),
        ],
    )
    block = parse_report(make_report(blocks=[flow])).blocks[0]
    assert isinstance(block, RequestFlow)

    assert [capture.name for step in block.steps for capture in step.captures] == [
        "access-token",
        "ACCESS_TOKEN",
    ]


def test_a_request_is_accepted_inside_a_panel() -> None:
    panel = {"type": "panel", "title": "Evidence", "blocks": [_request()]}

    report = parse_report(make_report(blocks=[panel]))
    outer = report.blocks[0]
    assert isinstance(outer, Panel)

    assert isinstance(outer.blocks[0], Request)


def test_a_command_request_needs_no_method_url_or_reader_field() -> None:
    block = parsed_request(make_command_request())

    assert (block.method, block.url, block.variables, block.command) == (
        None,
        None,
        [],
        "vault-run -- curl -s https://api.partner.example/v1/tiers | jq 'map({code, mapped})'",
    )


def test_a_command_keeps_its_inner_lines_and_drops_the_trailing_newline_a_block_scalar_adds() -> None:
    block = parsed_request(make_command_request(command="cd /srv\nrun --all\n"))

    assert block.command == "cd /srv\nrun --all"


@pytest.mark.parametrize(
    "composed",
    [
        {"method": "GET"},
        {"url": "https://api.example.com/a"},
        {"headers": {"Accept": "application/json"}},
        {"body": "{}"},
    ],
    ids=["method", "url", "headers", "body"],
)
def test_a_command_refuses_the_fields_a_composed_curl_is_built_from(composed: dict[str, Any]) -> None:
    field = next(iter(composed))
    with pytest.raises(ReportError, match=rf"sets `command` and `{field}`"):
        parse_report(make_report(blocks=[make_command_request(**composed)]))


@pytest.mark.parametrize("missing", ["method", "url"])
def test_a_request_without_a_command_still_needs_a_method_and_a_url(missing: str) -> None:
    block = make_request()
    del block[missing]
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[block]))

    assert str(raised.value).endswith(
        "request 'Read an endpoint' needs `method` and `url` to build a curl, or a `command` to run as "
        "written, or a `query` to record as written"
    )


def test_a_blank_command_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"blocks\.0\.request\.command: .*command must not be blank"):
        parse_report(make_report(blocks=[make_command_request(command="  \n")]))


def test_a_blank_case_command_is_rejected_at_the_case_it_sits_on() -> None:
    cases = [
        {"label": "finding", "response": {"body": "[]"}},
        {"label": "control", "command": "  \n", "response": {"body": "[]"}},
    ]
    with pytest.raises(
        ReportError, match=r"blocks\.0\.request\.cases\.1\.command: .*command must not be blank"
    ):
        parse_report(make_report(blocks=[make_command_request(cases=cases)]))


def test_a_command_note_on_a_request_that_builds_a_curl_is_rejected() -> None:
    with pytest.raises(ReportError, match=r"sets a command_note but runs no command"):
        parse_report(make_report(blocks=[make_request(command_note="Why the jq.")]))


def test_a_blank_command_note_is_rejected() -> None:
    with pytest.raises(
        ReportError,
        match=r"blocks\.0\.request\.command_note: String should match pattern '\\S'$",
    ):
        parse_report(make_report(blocks=[make_command_request(command_note="   ")]))


def test_a_flow_step_is_held_to_the_same_command_rules_as_a_request() -> None:
    steps = [
        make_step(command="vault-run -- mint-token", captures=[{"name": "token", "source": "body"}]),
        make_step(url="https://{{host}}/b", headers={"Authorization": "Bearer {{token}}"}),
    ]
    with pytest.raises(ReportError, match=r"sets `command` and `method`"):
        parse_report(make_report(blocks=[make_flow(steps=steps)]))


def test_asking_a_command_request_for_its_composed_call_raises() -> None:
    block = parsed_request(make_command_request())

    with pytest.raises(ReportError, match=r"runs a command, so skaldr composes no call for it"):
        block.composed_call()


def test_a_case_command_replaces_the_requests_for_that_case_alone() -> None:
    cases = [
        {"label": "finding", "response": {"body": "[]"}},
        {
            "label": "control",
            "command": "vault-run -- curl -s https://api.partner.example/v1/regions",
            "response": {"body": "[]"},
        },
    ]
    block = parsed_request(make_command_request(cases=cases))

    assert [compute.command_for(block, case) for case in block.cases] == [
        "vault-run -- curl -s https://api.partner.example/v1/tiers | jq 'map({code, mapped})'",
        "vault-run -- curl -s https://api.partner.example/v1/regions",
    ]


def test_a_case_command_needs_a_request_that_runs_a_command() -> None:
    cases = [{"label": "one", "command": "echo hi", "response": {"body": "hi"}}]
    with pytest.raises(ReportError, match=r"case 'one' sets a command but the request builds a curl"):
        parse_report(make_report(blocks=[make_request(cases=cases)]))


@pytest.mark.parametrize("field", ["headers", "headers_add"])
def test_a_case_of_a_command_request_cannot_set_headers(field: str) -> None:
    cases = [{"label": "one", field: {"Accept": "text/plain"}, "response": {"body": "x"}}]
    with pytest.raises(ReportError, match=rf"case 'one' sets `{field}` on a request that runs a command"):
        parse_report(make_report(blocks=[make_command_request(cases=cases)]))


def test_a_command_fills_the_case_axis_and_counts_its_tokens_as_used() -> None:
    block = parsed_request(
        make_command_request(
            command="vault-run -- curl -s 'https://{{host}}/v1/mappings?label={{label}}'",
            variables=[{"name": "host", "example": "api.partner.example"}],
            case_variable="label",
            cases=[{"label": "TIER", "response": {"body": "[]"}}],
        )
    )

    assert compute.command_for(block, block.cases[0]) == (
        "vault-run -- curl -s 'https://{{host}}/v1/mappings?label=TIER'"
    )


def test_a_variable_used_only_in_a_case_command_counts_as_used() -> None:
    cases = [{"label": "one", "command": "vault-run -- fetch {{region}}", "response": {"body": "x"}}]
    block = parsed_request(make_command_request(variables=[{"name": "region", "example": "eu"}], cases=cases))

    assert block.referenced_variables() == {"region"}


def test_a_case_tone_colours_a_case_that_recorded_no_status() -> None:
    cases = [{"label": "finding", "tone": "warning", "response": {"body": "[]"}}]
    block = parsed_request(make_command_request(cases=cases))

    assert compute.case_tone(block.cases[0]) == "warning"


def test_a_case_tone_is_refused_beside_a_status_that_already_decides_it() -> None:
    cases = [{"label": "one", "tone": "success", "response": {"status": 500, "body": "{}"}}]
    with pytest.raises(ReportError, match=r"case 'one' sets a tone and records status 500"):
        parse_report(make_report(blocks=[make_command_request(cases=cases)]))


def test_a_flow_step_may_run_a_command_and_capture_from_its_output() -> None:
    minting = {
        "label": "Mint a token",
        "command": "vault-run -- mint-token --audience partner",
        "captures": [{"name": "token", "source": "body"}],
        "cases": [{"label": "one", "response": {"body": "abc123"}}],
    }
    steps = [minting, make_step(url="https://{{host}}/b", headers={"Authorization": "Bearer {{token}}"})]

    flow = parse_report(make_report(blocks=[make_flow(steps=steps)])).blocks[0]
    assert isinstance(flow, RequestFlow)

    assert (
        compute.command_for(flow.steps[0], flow.steps[0].cases[0])
        == "vault-run -- mint-token --audience partner"
    )


def _query_error(**overrides: Any) -> str:
    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[make_query_request(**overrides)]))
    return str(raised.value)


def test_a_query_request_needs_no_method_url_or_reader_field() -> None:
    block = parsed_request(make_query_request())

    assert (block.method, block.url, block.command, block.variables) == (None, None, None, [])
    assert block.query is not None
    assert (block.query.runner, block.query.lang, block.query.content) == (
        "mongosh, orders database",
        "json",
        '[{"$match": {"status": "open"}}, {"$count": "n"}]',
    )


def test_a_query_keeps_its_inner_lines_and_drops_the_trailing_newline_a_block_scalar_adds() -> None:
    query = {"runner": "psql", "lang": "sql", "content": "SELECT 1\nFROM orders\n"}

    block = parsed_request(make_query_request(query=query))

    assert block.query is not None
    assert block.query.content == "SELECT 1\nFROM orders"


@pytest.mark.parametrize(
    "composed",
    [
        {"method": "GET"},
        {"url": "https://api.example.com/a"},
        {"headers": {"Accept": "application/json"}},
        {"body": "{}"},
        {"command": "mongosh --eval 'db.orders.count()'"},
    ],
    ids=["method", "url", "headers", "body", "command"],
)
def test_a_query_refuses_the_fields_a_curl_or_a_command_is_built_from(composed: dict[str, Any]) -> None:
    field = next(iter(composed))

    assert _query_error(**composed).endswith(
        f"request 'Open orders in the shop database' sets `query` and `{field}`: a query is recorded as "
        f"written, so skaldr builds no curl and `{field}` would never reach it"
    )


def test_a_query_needs_a_runner() -> None:
    query = {"lang": "json", "content": "[]"}

    assert "blocks.0.request.query.runner: Field required" in _query_error(query=query)


def test_a_query_needs_a_language() -> None:
    query = {"runner": "mongosh", "content": "[]"}

    assert "blocks.0.request.query.lang: Field required" in _query_error(query=query)


def test_a_blank_runner_is_rejected() -> None:
    query = {"runner": "  ", "lang": "json", "content": "[]"}

    assert "blocks.0.request.query.runner: String should match pattern '\\S'" in _query_error(query=query)


def test_a_blank_query_is_rejected() -> None:
    query = {"runner": "mongosh", "lang": "json", "content": "  \n"}

    assert "blocks.0.request.query.content: Value error, query must not be blank" in _query_error(query=query)


def test_a_language_pygments_has_no_lexer_for_is_rejected_by_name() -> None:
    query = {"runner": "mongosh", "lang": "no-such-lexer", "content": "[]"}

    assert "blocks.0.request.query.lang: Value error, `no-such-lexer` is not a Pygments lexer name" in (
        _query_error(query=query)
    )


def test_a_lexer_name_is_accepted_in_any_letter_case_and_kept_as_written() -> None:
    query = {"runner": "mongosh", "lang": "JSON", "content": "[]"}

    block = parsed_request(make_query_request(query=query))

    assert block.query is not None
    assert block.query.lang == "JSON"


@pytest.mark.parametrize("language", ["json", "sql", "postgresql", "js", "graphql"])
def test_any_pygments_lexer_name_is_accepted_as_the_query_language(language: str) -> None:
    query = {"runner": "a tool", "lang": language, "content": "x"}

    assert parsed_request(make_query_request(query=query)).query is not None


def test_a_command_note_on_a_query_request_is_rejected() -> None:
    assert _query_error(command_note="Why this pipeline.").endswith(
        "request 'Open orders in the shop database' sets a command_note on a query: put the note in a verdict"
    )


@pytest.mark.parametrize("field", ["command", "headers", "headers_add"])
def test_a_case_of_a_query_request_cannot_set_a_command_or_headers(field: str) -> None:
    value = "echo hi" if field == "command" else {"Accept": "text/plain"}
    cases = [{"label": "one", field: value, "response": {"body": "x"}}]

    assert _query_error(cases=cases).endswith(
        f"case 'one' sets `{field}` on a request that records a query, which has no command or headers "
        "of its own: write the change into the query"
    )


def test_a_case_cannot_override_the_query() -> None:
    query = {"runner": "x", "lang": "json", "content": "[]"}
    cases = [{"label": "one", "query": query, "response": {"body": "x"}}]

    assert "blocks.0.request.cases.0.query: Extra inputs are not permitted" in _query_error(cases=cases)


def test_a_query_counts_its_tokens_as_used_and_fills_the_case_axis() -> None:
    content = '[{"$match": {"status": "{{status}}", "region": "{{region}}"}}]'
    query = {"runner": "mongosh", "lang": "json", "content": content}
    block = parsed_request(
        make_query_request(
            query=query,
            variables=[{"name": "region"}],
            case_variable="status",
            cases=[{"label": "open", "response": {"body": "[]"}}],
        )
    )

    assert block.referenced_variables() == {"status", "region"}
    assert block.resolvable_variables() == {"region", "status"}


def test_a_variable_declared_but_never_used_by_the_query_is_rejected() -> None:
    assert _query_error(variables=[{"name": "region"}]).endswith(
        "request declares region but never uses it; every variable needs a `{{name}}` to fill"
    )


def test_a_flow_step_may_record_a_query_but_cannot_capture_from_it() -> None:
    step = make_step(captures=[{"name": "n", "source": "body"}])
    for field in ("method", "url"):
        del step[field]
    step["query"] = {"runner": "mongosh", "lang": "json", "content": "[]"}

    with pytest.raises(ReportError) as raised:
        parse_report(make_report(blocks=[make_flow(steps=[step])]))

    assert str(raised.value).endswith(
        "step 'A step' captures a value but records a query: a capture reads a response the reader pastes, "
        "and a query has nowhere to paste one"
    )
