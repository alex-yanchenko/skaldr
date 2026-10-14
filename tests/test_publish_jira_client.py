import re

import httpx2
import pytest
from pydantic import JsonValue

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.jira.api import (
    ChangeDetails,
    Changelog,
    ChangelogAuthor,
    Comment,
    CreatedIssue,
    EntityProperty,
    Issue,
    JiraUser,
    Status,
    StatusCategory,
    Transition,
)
from tests.factories.auth_factory import basic_auth_header, summarise
from tests.factories.jira_factory import CLOSE, FakeJira, Reply

SITE = "https://example.atlassian.net"
AUTHORIZATION = basic_auth_header("reader@example.com", "api-token")
PARAGRAPH: JsonValue = {"version": 1, "type": "doc", "content": [{"type": "paragraph"}]}
STAMP = EntityProperty(key="skaldr.stamp", value={"doc_id": "garden-handbook", "section_id": None})
ISSUE = "/rest/api/3/issue/DEMO-1"
CHANGELOG = f"{ISSUE}/changelog"
COMMENTS = f"{ISSUE}/comment"
CREATE = "/rest/api/3/issue"
MYSELF = "/rest/api/3/myself"


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
        CreatedIssue(key="DEMO-1"),
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
        Issue(key="DEMO-1", fields={"summary": "Garden handbook", "labels": ["garden"]}),
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

    assert (changelog, [summarise(request)["url"] for request in jira.requests]) == (
        [
            Changelog(
                id=f"1000{number}",
                author=ChangelogAuthor(accountId="account-editor", displayName="Robin Editor"),
                created=f"2026-10-0{number}T10:00:00.000+0000",
                items=[ChangeDetails(field="summary", fieldId="summary")],
            )
            for number in range(1, 6)
        ],
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
    jira.answer_next(
        "GET", CHANGELOG, Reply(200, {"startAt": 0, "maxResults": 100, "total": 9, "values": []})
    )

    assert (jira.client().changelog("DEMO-1"), len(jira.requests)) == ([], 1)


ONE_ENTRY: JsonValue = {"id": "10001", "items": [{"field": "summary", "fieldId": "summary"}]}


@pytest.mark.parametrize(
    "page",
    [
        pytest.param({"startAt": 0, "total": 1, "values": [ONE_ENTRY]}, id="total-without-is-last"),
        pytest.param({"startAt": 0, "isLast": True, "values": [ONE_ENTRY]}, id="is-last-without-total"),
    ],
)
def test_a_changelog_page_ends_the_read_on_either_its_total_or_its_last_flag(page: JsonValue) -> None:
    jira = _seeded()
    jira.answer_next("GET", CHANGELOG, Reply(200, page))

    assert (jira.client().changelog("DEMO-1"), len(jira.requests)) == (
        [Changelog(id="10001", items=[ChangeDetails(field="summary", fieldId="summary")])],
        1,
    )


def test_a_changelog_page_that_does_not_start_where_it_was_asked_to_is_an_error() -> None:
    jira = _seeded()
    stuck: JsonValue = {
        "startAt": 0,
        "total": 9,
        "isLast": False,
        "values": [{"id": "10001", "items": [{"field": "summary", "fieldId": "summary"}]}],
    }
    jira.answer_next("GET", CHANGELOG, Reply(200, stuck), Reply(200, stuck))

    with pytest.raises(
        ConnectorError,
        match=_exactly(
            "Jira answered GET /rest/api/3/issue/DEMO-1/changelog with a page starting at entry 0 when "
            "skaldr asked for entry 1, so skaldr cannot read the issue's whole history"
        ),
    ):
        jira.client().changelog("DEMO-1")
    assert len(jira.requests) == 2


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
    in_progress = Status(name="In Progress", statusCategory=StatusCategory(key="indeterminate"))
    status = jira.issues["DEMO-1"].fields["status"]
    assert (offered, done.is_done, in_progress.is_done, status, summarise(jira.requests[1])) == (
        [Transition(id="11", to=in_progress), Transition(id=CLOSE, to=done)],
        True,
        False,
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


def _rules(count: int) -> JsonValue:
    rules: list[JsonValue] = [{"type": "rule"}] * count
    return {"version": 1, "type": "doc", "content": rules}


def test_the_comments_are_read_page_by_page_to_the_end() -> None:
    jira = _seeded()
    client = jira.client()
    for count in range(3):
        client.add_comment("DEMO-1", _rules(count))
    jira.forget_requests()

    comments = client.comments("DEMO-1")

    assert (comments, [summarise(request)["url"] for request in jira.requests]) == (
        [Comment(id="1", body=_rules(0)), Comment(id="2", body=_rules(1)), Comment(id="3", body=_rules(2))],
        [
            f"{SITE}/rest/api/3/issue/DEMO-1/comment?startAt=0&maxResults=100",
            f"{SITE}/rest/api/3/issue/DEMO-1/comment?startAt=2&maxResults=100",
        ],
    )


def test_a_comments_page_that_does_not_start_where_it_was_asked_to_is_an_error() -> None:
    jira = _seeded()
    stuck: JsonValue = {"startAt": 0, "total": 9, "comments": [{"id": "1", "body": PARAGRAPH}]}
    jira.answer_next("GET", COMMENTS, Reply(200, stuck), Reply(200, stuck))

    with pytest.raises(
        ConnectorError,
        match=_exactly(
            "Jira answered GET /rest/api/3/issue/DEMO-1/comment with a page starting at entry 0 when skaldr "
            "asked for entry 1, so skaldr cannot read the issue's whole list of comments"
        ),
    ):
        jira.client().comments("DEMO-1")


def test_a_client_used_as_a_context_manager_closes_its_connections_on_leaving() -> None:
    jira = FakeJira()

    with jira.client() as client:
        account = client.myself()
        open_while_inside = jira.closes

    assert (account, open_while_inside, jira.closes) == (JiraUser(accountId="account-writer"), 0, 1)


def test_myself_names_the_signed_in_account() -> None:
    jira = FakeJira()

    assert (jira.client().myself(), jira.calls()) == (
        JiraUser(accountId="account-writer"),
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
    jira.answer_next("GET", ISSUE, Reply(429, {}, {"Retry-After": "7"}))

    issue = jira.client().get_issue("DEMO-1", ["summary"])

    assert (issue.fields, jira.sleeps, len(jira.requests)) == ({"summary": "Garden handbook"}, [7.0], 2)


def test_a_rate_limited_write_is_retried_too() -> None:
    jira = _seeded()
    jira.answer_next("PUT", ISSUE, Reply(429, {}, {"Retry-After": "1"}))

    jira.client().edit_issue("DEMO-1", {"summary": "Garden guide"})

    assert (jira.issues["DEMO-1"].fields["summary"], jira.sleeps, jira.calls()) == (
        "Garden guide",
        [1.0],
        [("PUT", "/rest/api/3/issue/DEMO-1"), ("PUT", "/rest/api/3/issue/DEMO-1")],
    )


def test_without_retry_after_the_wait_doubles_from_two_seconds() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, Reply(429), Reply(429, {}, {"Retry-After": "soon"}), Reply(503))

    jira.client().get_issue("DEMO-1", ["summary"])

    assert (jira.sleeps, len(jira.requests)) == ([2.0, 4.0, 8.0], 4)


def test_after_four_rate_limited_attempts_the_request_fails_naming_the_limit() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, *[Reply(429)] * 4)

    with pytest.raises(ConnectorError) as raised:
        jira.client().get_issue("DEMO-1", ["summary"])

    assert (type(raised.value), str(raised.value), jira.sleeps, len(jira.requests)) == (
        ConnectorError,
        "Jira kept refusing GET /rest/api/3/issue/DEMO-1 as too many requests (HTTP 429) after 4 attempts; "
        "wait a minute and publish again",
        [2.0, 4.0, 8.0],
        4,
    )


def test_a_retry_after_longer_than_a_minute_is_not_waited_for_and_is_quoted() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, Reply(429, {}, {"Retry-After": "3600"}))

    with pytest.raises(
        ConnectorError,
        match=_exactly(
            "Jira kept refusing GET /rest/api/3/issue/DEMO-1 as too many requests (HTTP 429) after 1 "
            "attempt; Jira asked to wait 3600 seconds, so publish again after that"
        ),
    ):
        jira.client().get_issue("DEMO-1", ["summary"])
    assert (jira.sleeps, len(jira.requests)) == ([], 1)


@pytest.mark.parametrize("call", ["create", "edit"])
def test_a_write_still_rate_limited_after_four_attempts_is_a_rejected_write(call: str) -> None:
    jira = _seeded()
    method, path = ("POST", CREATE) if call == "create" else ("PUT", ISSUE)
    jira.answer_next(method, path, *[Reply(429, {}, {"Retry-After": "1"})] * 4)
    client = jira.client()

    with pytest.raises(WriteRejectedError) as raised:
        if call == "create":
            client.create_issue({"summary": "Garden guide"}, [])
        else:
            client.edit_issue("DEMO-1", {"summary": "Garden guide"})

    assert (str(raised.value), jira.sleeps) == (
        f"Jira kept refusing {method} {path} as too many requests (HTTP 429) after 4 attempts; Jira asked "
        "to wait 1 second, so publish again after that",
        [1.0, 1.0, 1.0],
    )


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_server_error_on_a_read_is_retried(status: int) -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, Reply(status))

    jira.client().get_issue("DEMO-1", ["summary"])

    assert (jira.sleeps, len(jira.requests)) == ([2.0], 2)


def test_a_read_that_keeps_failing_on_jiras_side_fails_after_four_attempts() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, *[Reply(503, {"errorMessages": ["Service unavailable"]})] * 4)

    with pytest.raises(ConnectorError) as raised:
        jira.client().get_issue("DEMO-1", ["summary"])

    assert (type(raised.value), str(raised.value), jira.sleeps, len(jira.requests)) == (
        ConnectorError,
        "Jira answered HTTP 503 to GET /rest/api/3/issue/DEMO-1: Service unavailable",
        [2.0, 4.0, 8.0],
        4,
    )


def test_a_retry_after_of_exactly_a_minute_is_waited_for() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, Reply(429, {}, {"Retry-After": "60"}))

    issue = jira.client().get_issue("DEMO-1", ["summary"])

    assert (issue.fields, jira.sleeps, len(jira.requests)) == ({"summary": "Garden handbook"}, [60.0], 2)


def test_a_server_error_on_a_read_waits_as_long_as_its_retry_after_asks() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, Reply(503, {}, {"Retry-After": "30"}))

    issue = jira.client().get_issue("DEMO-1", ["summary"])

    assert (issue.fields, jira.sleeps, len(jira.requests)) == ({"summary": "Garden handbook"}, [30.0], 2)


def test_a_server_error_asking_to_wait_longer_than_a_minute_is_not_waited_for() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, Reply(503, {"errorMessages": ["Maintenance"]}, {"Retry-After": "3600"}))

    with pytest.raises(
        ConnectorError, match=_exactly("Jira answered HTTP 503 to GET /rest/api/3/issue/DEMO-1: Maintenance")
    ):
        jira.client().get_issue("DEMO-1", ["summary"])
    assert (jira.sleeps, len(jira.requests)) == ([], 1)


def test_a_refused_write_carrying_a_retry_after_is_not_retried() -> None:
    jira = _seeded()
    jira.answer_next("PUT", ISSUE, Reply(400, {"errorMessages": ["Bad summary"]}, {"Retry-After": "1"}))

    with pytest.raises(
        WriteRejectedError,
        match=_exactly("Jira refused PUT /rest/api/3/issue/DEMO-1 (HTTP 400): Bad summary"),
    ):
        jira.client().edit_issue("DEMO-1", {"summary": "Garden guide"})
    assert (jira.sleeps, len(jira.requests)) == ([], 1)


@pytest.mark.parametrize(
    ("call", "raised_type", "message"),
    [
        pytest.param(
            "create",
            WriteRejectedError,
            "Jira refused POST /rest/api/3/issue (HTTP 404): No project could be found with key 'DEMO'.",
            id="create",
        ),
        pytest.param(
            "myself",
            ConnectorError,
            "Jira refused GET /rest/api/3/myself (HTTP 404): No project could be found with key 'DEMO'.",
            id="myself",
        ),
    ],
)
def test_a_not_found_on_a_request_that_names_no_issue_is_a_refusal_not_a_missing_issue(
    call: str, raised_type: type[ConnectorError], message: str
) -> None:
    jira = FakeJira()
    method, path = ("POST", CREATE) if call == "create" else ("GET", MYSELF)
    jira.answer_next(
        method, path, Reply(404, {"errorMessages": ["No project could be found with key 'DEMO'."]})
    )
    client = jira.client()

    with pytest.raises(ConnectorError) as raised:
        if call == "create":
            client.create_issue({"summary": "Garden guide"}, [])
        else:
            client.myself()

    assert (type(raised.value), str(raised.value)) == (raised_type, message)


def test_a_server_error_on_a_write_is_not_retried_because_it_may_have_landed() -> None:
    jira = _seeded()
    jira.answer_next("PUT", ISSUE, Reply(503, {"errorMessages": ["Service unavailable"]}))

    with pytest.raises(
        ConnectorError,
        match=_exactly("Jira answered HTTP 503 to PUT /rest/api/3/issue/DEMO-1: Service unavailable"),
    ) as raised:
        jira.client().edit_issue("DEMO-1", {"summary": "Garden guide"})
    assert (type(raised.value), jira.sleeps, len(jira.requests)) == (ConnectorError, [], 1)


def test_a_dropped_connection_on_a_read_is_retried_and_on_a_write_is_not() -> None:
    jira = _seeded()
    dropped = httpx2.ConnectError("connection reset")
    jira.answer_next("GET", ISSUE, dropped)
    client = jira.client()

    client.get_issue("DEMO-1", ["summary"])
    jira.answer_next("PUT", ISSUE, dropped)
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


def test_an_answer_httpx_cannot_decode_is_a_connector_error_and_is_not_retried() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, httpx2.DecodingError("bad gzip stream"))

    with pytest.raises(ConnectorError) as raised:
        jira.client().get_issue("DEMO-1", ["summary"])

    assert (type(raised.value), str(raised.value), jira.sleeps, len(jira.requests)) == (
        ConnectorError,
        f"the request GET /rest/api/3/issue/DEMO-1 to Jira at {SITE} failed: bad gzip stream",
        [],
        1,
    )


def test_a_retry_after_in_digits_that_are_not_ascii_falls_back_to_the_doubling_wait() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, Reply(429, {}, {"Retry-After": "²".encode()}))

    issue = jira.client().get_issue("DEMO-1", ["summary"])

    assert (issue.fields, jira.sleeps, len(jira.requests)) == ({"summary": "Garden handbook"}, [2.0], 2)


def test_a_property_can_be_set_to_json_null() -> None:
    jira = _seeded()

    jira.client().put_property("DEMO-1", "skaldr.note", None)

    request = jira.requests[0]
    assert (request.content, request.headers["content-type"], jira.issues["DEMO-1"].properties) == (
        b"null",
        "application/json",
        {"skaldr.note": None},
    )


def test_a_read_that_never_connects_fails_after_four_attempts() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, *[httpx2.ConnectError("connection refused")] * 4)

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
    jira.answer_next("PUT", ISSUE, reply)

    with pytest.raises(WriteRejectedError, match=_exactly(message)):
        jira.client().edit_issue("DEMO-1", {"summary": "Garden guide"})


def test_a_refused_read_is_a_connector_error_and_not_a_rejected_write() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, Reply(403, {"errorMessages": ["Forbidden"]}))

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
    jira.answer_next(
        "GET" if method == "read" else "PUT", ISSUE, Reply(401, {"errorMessages": ["Unauthorized"]})
    )
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


def test_the_fake_keeps_a_queued_answer_for_the_request_it_was_queued_for() -> None:
    jira = _seeded()
    jira.answer_next("PUT", ISSUE, Reply(400, {"errorMessages": ["Bad summary"]}))
    client = jira.client()

    issue = client.get_issue("DEMO-1", ["summary"])
    with pytest.raises(
        WriteRejectedError,
        match=_exactly("Jira refused PUT /rest/api/3/issue/DEMO-1 (HTTP 400): Bad summary"),
    ):
        client.edit_issue("DEMO-1", {"summary": "Garden guide"})

    assert (issue.fields, jira.issues["DEMO-1"].fields["summary"]) == (
        {"summary": "Garden handbook"},
        "Garden handbook",
    )


def test_an_answer_skaldr_cannot_read_is_a_connector_error() -> None:
    jira = _seeded()
    jira.answer_next("GET", ISSUE, Reply(200, {"id": "10001"}))

    with pytest.raises(
        ConnectorError,
        match=_exactly("Jira's answer to GET /rest/api/3/issue/DEMO-1 is not the issue skaldr asked for"),
    ):
        jira.client().get_issue("DEMO-1", ["summary"])
