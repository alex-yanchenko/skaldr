import re

import httpx2
import pytest
from pydantic import JsonValue

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.jira.api import (
    ChangeDetails,
    Changelog,
    CreatedIssue,
    EntityProperty,
    Issue,
    JiraUser,
    Status,
    StatusCategory,
    Transition,
    UserDetails,
)
from tests.factories.auth_factory import basic_auth_header, summarise
from tests.factories.jira_factory import CLOSE, FakeJira, Reply

SITE = "https://example.atlassian.net"
AUTHORIZATION = basic_auth_header("reader@example.com", "api-token")
PARAGRAPH: JsonValue = {"version": 1, "type": "doc", "content": [{"type": "paragraph"}]}
STAMP = EntityProperty(key="skaldr.stamp", value={"doc_id": "garden-handbook", "section_id": None})


def _exactly(message: str) -> str:
    return f"^{re.escape(message)}$"


def _request(method: str, path: str, body: JsonValue = None) -> dict[str, object]:
    return {
        "method": method,
        "url": f"{SITE}{path}",
        "authorization": AUTHORIZATION,
        "content_type": None if body is None else "application/json",
        "body": body,
    }


def _seeded() -> FakeJira:
    jira = FakeJira()
    jira.seed("DEMO-1", summary="Garden handbook", description=PARAGRAPH, labels=["garden"])
    return jira


def test_creating_an_issue_posts_its_fields_and_properties_with_basic_auth() -> None:
    jira = FakeJira()

    created = jira.client().create_issue(
        {"project": {"key": "DEMO"}, "issuetype": {"name": "Task"}, "summary": "Garden handbook"}, [STAMP]
    )

    assert (created, [summarise(request) for request in jira.requests]) == (
        CreatedIssue(id="10001", key="DEMO-1"),
        [
            _request(
                "POST",
                "/rest/api/3/issue",
                {
                    "fields": {
                        "project": {"key": "DEMO"},
                        "issuetype": {"name": "Task"},
                        "summary": "Garden handbook",
                    },
                    "properties": [
                        {"key": "skaldr.stamp", "value": {"doc_id": "garden-handbook", "section_id": None}}
                    ],
                },
            )
        ],
    )
    assert jira.requests[0].headers["accept"] == "application/json"


def test_reading_an_issue_asks_for_the_named_fields_only() -> None:
    jira = _seeded()

    issue = jira.client().get_issue("DEMO-1", ["summary", "labels"])

    assert (issue, [summarise(request) for request in jira.requests]) == (
        Issue(id="10001", key="DEMO-1", fields={"summary": "Garden handbook", "labels": ["garden"]}),
        [_request("GET", "/rest/api/3/issue/DEMO-1?fields=summary%2Clabels")],
    )


def test_editing_an_issue_puts_the_fields_and_properties_it_is_given() -> None:
    jira = _seeded()

    jira.client().edit_issue("DEMO-1", {"summary": "Garden guide", "labels": None}, [STAMP])

    assert [summarise(request) for request in jira.requests] == [
        _request(
            "PUT",
            "/rest/api/3/issue/DEMO-1",
            {
                "fields": {"summary": "Garden guide", "labels": None},
                "properties": [
                    {"key": "skaldr.stamp", "value": {"doc_id": "garden-handbook", "section_id": None}}
                ],
            },
        )
    ]


def test_an_edit_without_properties_sends_fields_alone() -> None:
    jira = _seeded()

    jira.client().edit_issue("DEMO-1", {"summary": "Garden guide"})

    assert [summarise(request)["body"] for request in jira.requests] == [
        {"fields": {"summary": "Garden guide"}}
    ]


def test_the_changelog_is_read_page_by_page_to_the_end() -> None:
    jira = _seeded()
    for count in range(5):
        jira.edit_by_hand("DEMO-1", summary=f"Garden handbook {count}")
    jira.forget_requests()

    changelog = jira.client().changelog("DEMO-1")

    assert (
        [entry.id for entry in changelog],
        changelog[0],
        [summarise(request)["url"] for request in jira.requests],
    ) == (
        ["10001", "10002", "10003", "10004", "10005"],
        Changelog(
            id="10001",
            author=UserDetails(accountId="account-editor", displayName="Robin Editor"),
            created="2026-10-01T10:00:00.000+0000",
            items=[ChangeDetails(field="summary", fieldId="summary")],
        ),
        [
            f"{SITE}/rest/api/3/issue/DEMO-1/changelog?startAt=0&maxResults=100",
            f"{SITE}/rest/api/3/issue/DEMO-1/changelog?startAt=2&maxResults=100",
            f"{SITE}/rest/api/3/issue/DEMO-1/changelog?startAt=4&maxResults=100",
        ],
    )


def test_an_empty_changelog_is_one_request() -> None:
    jira = _seeded()

    assert (jira.client().changelog("DEMO-1"), jira.calls()) == (
        [],
        [("GET", "/rest/api/3/issue/DEMO-1/changelog")],
    )


def test_a_changelog_page_that_returns_nothing_ends_the_read_even_when_it_claims_more() -> None:
    jira = _seeded()
    jira.answer_next(Reply(200, {"startAt": 0, "maxResults": 100, "total": 9, "values": []}))

    assert (jira.client().changelog("DEMO-1"), len(jira.requests)) == ([], 1)


def test_an_issue_property_is_read_and_written_as_its_json_value() -> None:
    jira = _seeded()
    client = jira.client()

    missing = client.get_property("DEMO-1", "skaldr.stamp")
    client.put_property("DEMO-1", "skaldr.stamp", {"doc_id": "garden-handbook"})
    found = client.get_property("DEMO-1", "skaldr.stamp")

    assert (missing, found, [summarise(request) for request in jira.requests]) == (
        None,
        EntityProperty(key="skaldr.stamp", value={"doc_id": "garden-handbook"}),
        [
            _request("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
            _request(
                "PUT", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp", {"doc_id": "garden-handbook"}
            ),
            _request("GET", "/rest/api/3/issue/DEMO-1/properties/skaldr.stamp"),
        ],
    )


def test_transitions_are_listed_and_one_is_taken() -> None:
    jira = _seeded()
    client = jira.client()

    offered = client.transitions("DEMO-1")
    client.transition("DEMO-1", CLOSE)

    done = Status(name="Done", statusCategory=StatusCategory(key="done"))
    status = jira.issues["DEMO-1"].fields["status"]
    assert (offered[1], done.is_done, status, summarise(jira.requests[1])) == (
        Transition(id=CLOSE, name="Close", to=done),
        True,
        {"name": "Done", "statusCategory": {"key": "done"}},
        _request("POST", "/rest/api/3/issue/DEMO-1/transitions", {"transition": {"id": CLOSE}}),
    )


def test_a_comment_is_posted_as_adf() -> None:
    jira = _seeded()

    jira.client().add_comment("DEMO-1", PARAGRAPH)

    assert (jira.issues["DEMO-1"].comments, summarise(jira.requests[0])) == (
        [PARAGRAPH],
        _request("POST", "/rest/api/3/issue/DEMO-1/comment", {"body": PARAGRAPH}),
    )


def test_myself_names_the_signed_in_account() -> None:
    jira = FakeJira()

    assert (jira.client().myself(), jira.calls()) == (
        JiraUser(accountId="account-writer", displayName="Example Reader"),
        [("GET", "/rest/api/3/myself")],
    )


def test_an_issue_key_is_escaped_in_the_path() -> None:
    jira = FakeJira()

    with pytest.raises(ItemNotFoundError):
        jira.client().get_issue("DEMO-1/../2", ["summary"])

    assert [str(request.url) for request in jira.requests] == [
        f"{SITE}/rest/api/3/issue/DEMO-1%2F..%2F2?fields=summary"
    ]


def test_a_rate_limited_request_waits_as_long_as_retry_after_asks_then_retries() -> None:
    jira = _seeded()
    jira.answer_next(Reply(429, {}, {"Retry-After": "7"}))

    issue = jira.client().get_issue("DEMO-1", ["summary"])

    assert (issue.fields, jira.sleeps, len(jira.requests)) == ({"summary": "Garden handbook"}, [7.0], 2)


def test_a_rate_limited_write_is_retried_too() -> None:
    jira = _seeded()
    jira.answer_next(Reply(429, {}, {"Retry-After": "1"}))

    jira.client().edit_issue("DEMO-1", {"summary": "Garden guide"})

    assert (jira.issues["DEMO-1"].fields["summary"], jira.sleeps, jira.calls()) == (
        "Garden guide",
        [1.0],
        [("PUT", "/rest/api/3/issue/DEMO-1"), ("PUT", "/rest/api/3/issue/DEMO-1")],
    )


def test_without_retry_after_the_wait_doubles_from_two_seconds() -> None:
    jira = _seeded()
    jira.answer_next(Reply(429), Reply(429, {}, {"Retry-After": "soon"}), Reply(503))

    jira.client().get_issue("DEMO-1", ["summary"])

    assert (jira.sleeps, len(jira.requests)) == ([2.0, 4.0, 8.0], 4)


def test_after_four_rate_limited_attempts_the_request_fails_naming_the_limit() -> None:
    jira = _seeded()
    jira.answer_next(*[Reply(429)] * 4)

    with pytest.raises(
        ConnectorError,
        match=_exactly(
            "Jira kept refusing GET /rest/api/3/issue/DEMO-1 as too many requests (HTTP 429) after 4 "
            "attempts; wait a minute and publish again"
        ),
    ):
        jira.client().get_issue("DEMO-1", ["summary"])
    assert (jira.sleeps, len(jira.requests)) == ([2.0, 4.0, 8.0], 4)


def test_a_retry_after_longer_than_a_minute_is_not_waited_for() -> None:
    jira = _seeded()
    jira.answer_next(Reply(429, {}, {"Retry-After": "3600"}))

    with pytest.raises(
        ConnectorError,
        match=_exactly(
            "Jira kept refusing GET /rest/api/3/issue/DEMO-1 as too many requests (HTTP 429) after 1 "
            "attempt; wait a minute and publish again"
        ),
    ):
        jira.client().get_issue("DEMO-1", ["summary"])
    assert (jira.sleeps, len(jira.requests)) == ([], 1)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_server_error_on_a_read_is_retried(status: int) -> None:
    jira = _seeded()
    jira.answer_next(Reply(status))

    jira.client().get_issue("DEMO-1", ["summary"])

    assert (jira.sleeps, len(jira.requests)) == ([2.0], 2)


def test_a_server_error_on_a_write_is_not_retried_because_it_may_have_landed() -> None:
    jira = _seeded()
    jira.answer_next(Reply(503, {"errorMessages": ["Service unavailable"]}))

    with pytest.raises(
        ConnectorError,
        match=_exactly("Jira answered HTTP 503 to PUT /rest/api/3/issue/DEMO-1: Service unavailable"),
    ) as raised:
        jira.client().edit_issue("DEMO-1", {"summary": "Garden guide"})
    assert (type(raised.value), jira.sleeps, len(jira.requests)) == (ConnectorError, [], 1)


def test_a_dropped_connection_on_a_read_is_retried_and_on_a_write_is_not() -> None:
    jira = _seeded()
    dropped = httpx2.ConnectError("connection reset")
    jira.answer_next(dropped)
    client = jira.client()

    client.get_issue("DEMO-1", ["summary"])
    jira.answer_next(dropped)
    with pytest.raises(
        ConnectorError,
        match=_exactly(f"could not reach Jira at {SITE} for PUT /rest/api/3/issue/DEMO-1: connection reset"),
    ):
        client.edit_issue("DEMO-1", {"summary": "Garden guide"})

    assert (jira.sleeps, jira.calls()) == (
        [2.0],
        [
            ("GET", "/rest/api/3/issue/DEMO-1"),
            ("GET", "/rest/api/3/issue/DEMO-1"),
            ("PUT", "/rest/api/3/issue/DEMO-1"),
        ],
    )


def test_a_read_that_never_connects_fails_after_four_attempts() -> None:
    jira = _seeded()
    jira.answer_next(*[httpx2.ConnectError("connection refused")] * 4)

    with pytest.raises(
        ConnectorError,
        match=_exactly(
            f"could not reach Jira at {SITE} for GET /rest/api/3/issue/DEMO-1: connection refused"
        ),
    ):
        jira.client().get_issue("DEMO-1", ["summary"])
    assert jira.sleeps == [2.0, 4.0, 8.0]


def test_a_missing_issue_is_item_not_found() -> None:
    with pytest.raises(
        ItemNotFoundError,
        match=_exactly(
            "Jira has no issue DEMO-9 that this account can see (HTTP 404 to GET /rest/api/3/issue/DEMO-9)"
        ),
    ):
        FakeJira().client().get_issue("DEMO-9", ["summary"])


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        pytest.param(
            Reply(400, {"errorMessages": [], "errors": {"issuetype": "Specify a valid issue type"}}),
            "Jira refused PUT /rest/api/3/issue/DEMO-1 (HTTP 400): issuetype: Specify a valid issue type",
            id="bad-field",
        ),
        pytest.param(
            Reply(403, {"errorMessages": ["You do not have permission to edit issues in this project."]}),
            "Jira refused PUT /rest/api/3/issue/DEMO-1 (HTTP 403): You do not have permission to edit issues "
            "in this project.",
            id="forbidden",
        ),
        pytest.param(
            Reply(422, None),
            "Jira refused PUT /rest/api/3/issue/DEMO-1 (HTTP 422)",
            id="no-detail",
        ),
    ],
)
def test_a_definite_refusal_of_a_write_is_write_rejected(reply: Reply, message: str) -> None:
    jira = _seeded()
    jira.answer_next(reply)

    with pytest.raises(WriteRejectedError, match=_exactly(message)):
        jira.client().edit_issue("DEMO-1", {"summary": "Garden guide"})


def test_a_refused_read_is_a_connector_error_and_not_a_rejected_write() -> None:
    jira = _seeded()
    jira.answer_next(Reply(403, {"errorMessages": ["Forbidden"]}))

    with pytest.raises(ConnectorError) as raised:
        jira.client().get_issue("DEMO-1", ["summary"])

    assert (type(raised.value), str(raised.value)) == (
        ConnectorError,
        "Jira refused GET /rest/api/3/issue/DEMO-1 (HTTP 403): Forbidden",
    )


@pytest.mark.parametrize(
    ("method", "raised_type"),
    [("read", ConnectorError), ("write", WriteRejectedError)],
    ids=["read", "write-that-never-landed"],
)
def test_a_rejected_sign_in_says_to_sign_in_again(method: str, raised_type: type[ConnectorError]) -> None:
    jira = _seeded()
    jira.answer_next(Reply(401, {"errorMessages": ["Unauthorized"]}))
    client = jira.client()

    with pytest.raises(ConnectorError) as raised:
        if method == "read":
            client.get_issue("DEMO-1", ["summary"])
        else:
            client.edit_issue("DEMO-1", {"summary": "Garden guide"})

    assert (type(raised.value), str(raised.value)) == (
        raised_type,
        f"Jira at {SITE} rejected the sign-in (HTTP 401); the API token may have expired or been revoked, "
        "so run `skaldr auth jira`",
    )


def test_an_answer_skaldr_cannot_read_is_a_connector_error() -> None:
    jira = _seeded()
    jira.answer_next(Reply(200, {"key": "DEMO-1"}))

    with pytest.raises(
        ConnectorError,
        match=_exactly("Jira's answer to GET /rest/api/3/issue/DEMO-1 is not the issue skaldr asked for"),
    ):
        jira.client().get_issue("DEMO-1", ["summary"])
