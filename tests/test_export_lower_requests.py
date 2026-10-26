from skaldr.export.inline import bold, italic, plain
from skaldr.export.tree import Callout, CodeBlock, Heading, ListEntry, ListNode, Paragraph, Tab, Tabs
from skaldr.richtext import Code, Plain
from tests.factories import lowered, make_command_request, make_query_request, make_request


def test_a_request_with_one_case_shows_its_label_note_status_and_verdict() -> None:
    request = make_command_request(
        command_note="needs the vault",
        cases=[{"label": "all", "verdict": "fine", "response": {"status": 200, "body": "ok"}}],
    )

    assert lowered([request]) == (
        Paragraph(bold("Tier mappings on the partner API")),
        Paragraph(italic(plain("all"))),
        CodeBlock(request["command"], "bash"),
        Paragraph(italic((Plain("needs the vault"),)), "muted"),
        Paragraph((*bold("Recorded output"), Plain(": "), Plain("200 OK"))),
        CodeBlock("ok", ""),
        Callout("success", (Paragraph((*bold("Verdict"), Plain(": "), Plain("fine"))),)),
    )


def test_a_query_request_shows_its_runner_and_the_query_in_its_own_language() -> None:
    request = make_query_request(
        query={"runner": "psql, reporting replica", "lang": "sql", "content": "SELECT 1 WHERE s = '{{s}}'"},
        case_variable="s",
        cases=[{"label": "open", "verdict": "fine", "response": {"body": "1"}}],
    )

    assert lowered([request]) == (
        Paragraph(bold("Open orders in the shop database")),
        Paragraph(italic(plain("open"))),
        Paragraph((*bold("Query"), Plain(": "), Plain("psql, reporting replica"))),
        CodeBlock("SELECT 1 WHERE s = 'open'", "sql"),
        Paragraph(bold("Recorded output")),
        CodeBlock("1", "json"),
        Callout("neutral", (Paragraph((*bold("Verdict"), Plain(": "), Plain("fine"))),)),
    )


READ_WIDGETS = "curl -i -X GET \\\n  -H 'Accept: application/json' \\\n  'https://{{host}}/widgets'"


def test_a_request_lists_its_labelled_variables_and_shows_a_case_with_no_status_line() -> None:
    request = make_request(
        variables=[{"name": "host", "label": "API host", "example": "api.example.com"}],
        cases=[{"label": "one", "response": {"headers": {"content-type": "text/plain"}, "body": "ok"}}],
    )

    assert lowered([request]) == (
        Paragraph(bold("Read an endpoint")),
        Paragraph(bold("Values you supply")),
        ListNode(
            "bullet",
            (ListEntry((Code("{{host}}"), Plain(" "), Plain("API host: for example api.example.com"))),),
        ),
        Paragraph(italic(plain("one"))),
        CodeBlock(READ_WIDGETS, "bash"),
        Paragraph((*bold("Recorded response"), Plain(": "), Plain("no status line"))),
        CodeBlock("content-type: text/plain\n\nok", "http"),
    )


def test_a_verdict_on_one_case_of_several_sits_in_that_case_tab() -> None:
    request = make_request(
        variables=[],
        url="https://api.example.com/widgets",
        cases=[
            {"label": "missing", "verdict": "a **gap**", "response": {"status": 404, "body": "{}"}},
            {"label": "found", "response": {"status": 200, "body": "[]"}},
        ],
    )
    command = "curl -i -X GET \\\n  -H 'Accept: application/json' \\\n  https://api.example.com/widgets"

    assert lowered([request]) == (
        Paragraph(bold("Read an endpoint")),
        Tabs(
            (
                Tab(
                    (Plain("missing"),),
                    (
                        CodeBlock(command, "bash"),
                        Paragraph((*bold("Recorded response"), Plain(": "), Plain("404 Not Found"))),
                        CodeBlock("{}", "json"),
                        Callout(
                            "warning",
                            (Paragraph((*bold("Verdict"), Plain(": "), Plain("a "), *bold("gap"))),),
                        ),
                    ),
                    "warning",
                ),
                Tab(
                    (Plain("found"),),
                    (
                        CodeBlock(command, "bash"),
                        Paragraph((*bold("Recorded response"), Plain(": "), Plain("200 OK"))),
                        CodeBlock("[]", "json"),
                    ),
                    "success",
                ),
            ),
            "request cases",
        ),
    )


def test_a_request_with_several_cases_is_tabs() -> None:
    request = make_command_request(
        command="list",
        cases=[
            {"label": "a", "tone": "warning", "response": {"body": "x"}},
            {"label": "b", "tone": "success", "response": {"body": "y"}},
        ],
    )

    assert lowered([request]) == (
        Paragraph(bold("Tier mappings on the partner API")),
        Tabs(
            (
                Tab(
                    (Plain("a"),),
                    (CodeBlock("list", "bash"), Paragraph(bold("Recorded output")), CodeBlock("x", "")),
                    "warning",
                ),
                Tab(
                    (Plain("b"),),
                    (CodeBlock("list", "bash"), Paragraph(bold("Recorded output")), CodeBlock("y", "")),
                    "success",
                ),
            ),
            "request cases",
        ),
    )


def test_a_request_flow_names_each_step_its_captures_and_never_shows_a_secret_value() -> None:
    flow = {
        "type": "request_flow",
        "label": "Token then read",
        "variables": [
            {"name": "host", "example": "api.example.com"},
            {"name": "key", "secret": True, "example": "do-not-print"},
            {"name": "who"},
        ],
        "steps": [
            {
                "label": "Get token",
                "method": "POST",
                "url": "https://{{host}}/t",
                "headers": {"X-Key": "{{key}}", "X-Who": "{{who}}"},
                "captures": [
                    {"name": "token", "json_path": "$.data.access_token"},
                    {"name": "expires", "source": "body"},
                ],
                "cases": [{"label": "one", "response": {"status": 200, "body": "{}"}}],
            },
            {
                "label": "Read",
                "method": "GET",
                "url": "https://{{host}}/r",
                "headers": {"Authorization": "Bearer {{token}}", "X-Expires": "{{expires}}"},
                "cases": [
                    {
                        "label": "one",
                        "response": {
                            "status": 200,
                            "headers": {"content-type": ["application/json", "charset=utf-8"]},
                            "body": "{}",
                        },
                    }
                ],
            },
        ],
    }

    assert lowered([flow]) == (
        Paragraph(bold("Token then read")),
        Paragraph(bold("Values you supply")),
        ListNode(
            "bullet",
            (
                ListEntry((Code("{{host}}"), Plain(" "), Plain("host: for example api.example.com"))),
                ListEntry((Code("{{key}}"), Plain(" "), Plain("key: a secret, supply your own"))),
                ListEntry((Code("{{who}}"), Plain(" "), Plain("who: supply a value"))),
            ),
        ),
        Paragraph(
            (
                *bold("Step 1 of 2: Get token"),
                Plain(", captures "),
                Code("token"),
                Plain(" from "),
                Code("$.data.access_token"),
                Plain(", "),
                Code("expires"),
                Plain(" from the whole response body"),
            )
        ),
        Paragraph(italic(plain("one"))),
        CodeBlock(
            "curl -i -X POST \\\n  -H 'X-Key: {{key}}' \\\n  -H 'X-Who: {{who}}' \\\n  'https://{{host}}/t'",
            "bash",
        ),
        Paragraph((*bold("Recorded response"), Plain(": "), Plain("200 OK"))),
        CodeBlock("{}", "json"),
        Paragraph(bold("Step 2 of 2: Read")),
        Paragraph(italic(plain("one"))),
        CodeBlock(
            "curl -i -X GET \\\n  -H 'Authorization: Bearer {{token}}' \\\n  -H 'X-Expires: {{expires}}' \\\n"
            "  'https://{{host}}/r'",
            "bash",
        ),
        Paragraph((*bold("Recorded response"), Plain(": "), Plain("200 OK"))),
        CodeBlock("content-type: application/json\ncontent-type: charset=utf-8\n\n{}", "http"),
    )


def test_a_tabs_block_is_the_tabs_node_requests_use_with_each_tab_tone() -> None:
    block = {
        "type": "tabs",
        "tabs": [
            {"label": "Floor", "tone": "warning", "blocks": [{"type": "text", "body": "a"}]},
            {"label": "System", "blocks": [{"type": "heading", "level": 3, "text": "Scan"}]},
        ],
    }

    assert lowered([block]) == (
        Tabs(
            (
                Tab((Plain("Floor"),), (Paragraph((Plain("a"),)),), "warning"),
                Tab((Plain("System"),), (Heading(3, (Plain("Scan"),), "scan"),)),
            )
        ),
    )
