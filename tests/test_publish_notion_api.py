import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx2
import pytest

from skaldr.errors import AuthError, ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.notion.api import NOTION_VERSION, NotionApi
from skaldr.publish.notion.responses import PageMarkdown, User
from skaldr.publish_block.target import JsonFields
from tests.factories.auth_factory import rendered_traceback

PAGE_ID = "11111111-2222-4333-8444-555555555555"
PAGE: dict[str, Any] = {
    "object": "page",
    "id": PAGE_ID,
    "last_edited_time": "2026-10-09T12:00:00.000Z",
    "last_edited_by": {"object": "user", "id": "bot-1"},
    "in_trash": False,
    "properties": {},
}
MARKDOWN: dict[str, Any] = {
    "object": "page_markdown",
    "id": PAGE_ID,
    "markdown": "Welcome.",
    "truncated": False,
    "unknown_block_ids": [],
}
BOT: dict[str, Any] = {"object": "user", "id": "bot-1", "type": "bot", "name": "skaldr", "avatar_url": None}


def _task(status: str, **extra: Any) -> dict[str, Any]:
    return {
        "object": "async_task",
        "id": "task-1",
        "status": status,
        "status_url": "https://api.notion.com/v1/async_tasks/task-1",
        "created_time": "2026-10-09T12:00:00.000Z",
        "operation": {"surface": "rest", "name": "POST /v1/pages"},
        **extra,
    }


def _error(status: int, code: str, message: str) -> dict[str, Any]:
    return {"object": "error", "status": status, "code": code, "message": message}


@dataclass(frozen=True)
class Answer:
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict[str, str])
    failure: type[httpx2.TransportError] | None = None


def _failing(failure: type[httpx2.TransportError]) -> Answer:
    return Answer(0, None, failure=failure)


@dataclass(frozen=True)
class Sent:
    method: str
    url: str
    authorization: str | None
    version: str | None
    body: Any


@dataclass
class ScriptedNotion:
    answers: list[Answer]
    sent: list[Sent] = field(default_factory=list[Sent])

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(
            Sent(
                request.method,
                str(request.url),
                request.headers.get("authorization"),
                request.headers.get("notion-version"),
                json.loads(request.content) if request.content else None,
            )
        )
        answer = self.answers.pop(0)
        if answer.failure is not None:
            raise answer.failure(
                "timed out" if "Timeout" in answer.failure.__name__ else "reset", request=request
            )
        return httpx2.Response(answer.status, json=answer.body, headers=answer.headers)


@dataclass
class CountingTokens:
    tokens: Iterator[str]
    current: str = "first-token"
    renewals: int = 0

    @property
    def access_token(self) -> str:
        return self.current

    def renew(self) -> None:
        self.renewals += 1
        self.current = next(self.tokens)


@dataclass
class Harness:
    notion: ScriptedNotion
    tokens: CountingTokens
    sleeps: list[float]
    api: NotionApi


def _harness(*answers: Answer) -> Harness:
    notion = ScriptedNotion(list(answers))
    tokens = CountingTokens(iter(["second-token", "third-token"]))
    sleeps: list[float] = []
    api = NotionApi(tokens, transport=httpx2.MockTransport(notion), sleep=sleeps.append)
    return Harness(notion, tokens, sleeps, api)


def _get(url: str, token: str = "Bearer first-token") -> Sent:
    return Sent("GET", url, token, NOTION_VERSION, None)


def test_a_read_sends_the_bearer_token_and_the_notion_version_and_parses_the_answer() -> None:
    harness = _harness(Answer(200, BOT))

    assert harness.api.me() == User.model_validate(BOT)
    assert harness.notion.sent == [_get("https://api.notion.com/v1/users/me")]


def test_the_api_version_is_the_one_the_markdown_endpoints_need() -> None:
    assert NOTION_VERSION == "2026-03-11"


def test_a_markdown_update_asks_for_an_async_task_and_returns_a_synchronous_answer_as_it_is() -> None:
    harness = _harness(Answer(200, MARKDOWN))
    command: JsonFields = {
        "type": "update_content",
        "update_content": {"content_updates": [{"old_str": "a", "new_str": "b"}]},
    }

    markdown = harness.api.update_markdown(PAGE_ID, command)

    assert (markdown, harness.notion.sent, harness.sleeps) == (
        PageMarkdown.model_validate(MARKDOWN),
        [
            Sent(
                "PATCH",
                f"https://api.notion.com/v1/pages/{PAGE_ID}/markdown",
                "Bearer first-token",
                NOTION_VERSION,
                {**command, "allow_async": True},
            )
        ],
        [],
    )


def test_a_create_answered_with_an_async_task_is_polled_until_it_succeeds() -> None:
    harness = _harness(
        Answer(202, _task("queued", poll_after_seconds=2)),
        Answer(200, _task("running", poll_after_seconds=3)),
        Answer(200, _task("succeeded", result=PAGE)),
    )
    body: JsonFields = {"parent": {"page_id": PAGE_ID}, "markdown": "Welcome."}

    page = harness.api.create_page(body)

    assert (page.id, harness.notion.sent, harness.sleeps) == (
        PAGE_ID,
        [
            Sent(
                "POST",
                "https://api.notion.com/v1/pages",
                "Bearer first-token",
                NOTION_VERSION,
                {**body, "allow_async": True},
            ),
            _get("https://api.notion.com/v1/async_tasks/task-1"),
            _get("https://api.notion.com/v1/async_tasks/task-1"),
        ],
        [2.0, 3.0],
    )


def test_a_task_that_asks_for_no_pause_is_still_polled_after_a_short_one() -> None:
    harness = _harness(
        Answer(202, _task("queued", poll_after_seconds=0)), Answer(200, _task("succeeded", result=PAGE))
    )

    harness.api.create_page({"parent": {"page_id": PAGE_ID}})

    assert harness.sleeps == [0.5]


def test_a_failed_async_task_is_refused_like_the_same_error_answered_at_once() -> None:
    failed = _task("failed", error=_error(400, "validation_error", "No matches found for old_str"))
    harness = _harness(Answer(202, _task("queued", poll_after_seconds=1)), Answer(200, failed))

    with pytest.raises(
        WriteRejectedError,
        match=rf"^Notion refused to change the content of page {PAGE_ID}: No matches found for old_str "
        r"\(validation_error\)$",
    ):
        harness.api.update_markdown(PAGE_ID, {"type": "replace_content", "replace_content": {"new_str": ""}})


def test_a_task_still_running_after_ten_minutes_is_reported_as_unfinished() -> None:
    harness = _harness(
        Answer(202, _task("queued", poll_after_seconds=400)),
        Answer(200, _task("running", poll_after_seconds=400)),
    )

    with pytest.raises(
        ConnectorError,
        match=r"^Notion had not finished creating a page after 400 seconds \(task task-1\); the change may "
        r"still land, so read the page before publishing again$",
    ):
        harness.api.create_page({"parent": {"page_id": PAGE_ID}})
    assert harness.sleeps == [400.0]


def test_a_rate_limited_request_waits_as_long_as_retry_after_says_and_tries_again() -> None:
    limited = Answer(429, _error(429, "rate_limited", "slow down"), {"Retry-After": "2"})
    harness = _harness(limited, limited, Answer(200, BOT))

    harness.api.me()

    assert (harness.sleeps, len(harness.notion.sent)) == ([2.0, 2.0], 3)


def test_a_retry_without_retry_after_backs_off_exponentially() -> None:
    busy = Answer(529, _error(529, "service_unavailable", "busy"))
    harness = _harness(busy, busy, busy, Answer(200, PAGE))

    harness.api.update_page(PAGE_ID, {"in_trash": True})

    assert harness.sleeps == [1.0, 2.0, 4.0]


def test_a_server_error_on_a_read_is_retried_up_to_six_attempts_then_reported() -> None:
    failing = Answer(502, _error(502, "bad_gateway", "upstream"))
    harness = _harness(*[failing] * 6)

    with pytest.raises(
        ConnectorError, match=rf"^Notion could not read page {PAGE_ID}: HTTP 502 bad_gateway: upstream$"
    ):
        harness.api.page(PAGE_ID)
    assert (len(harness.notion.sent), harness.sleeps) == (6, [1.0, 2.0, 4.0, 8.0, 16.0])


def test_a_server_error_on_a_write_is_not_retried_because_the_write_may_have_landed() -> None:
    harness = _harness(Answer(500, _error(500, "internal_server_error", "oops")))

    with pytest.raises(ConnectorError) as caught:
        harness.api.update_page(PAGE_ID, {"in_trash": True})

    assert (type(caught.value), str(caught.value), len(harness.notion.sent)) == (
        ConnectorError,
        f"Notion could not change page {PAGE_ID}: HTTP 500 internal_server_error: oops",
        1,
    )


def test_a_request_still_rate_limited_after_six_attempts_is_refused() -> None:
    limited = Answer(429, _error(429, "rate_limited", "slow down"), {"Retry-After": "1"})
    harness = _harness(*[limited] * 6)

    with pytest.raises(
        WriteRejectedError, match=rf"^Notion refused to change page {PAGE_ID}: slow down \(rate_limited\)$"
    ):
        harness.api.update_page(PAGE_ID, {"in_trash": True})
    assert len(harness.notion.sent) == 6


def test_a_refused_token_is_renewed_once_and_the_request_sent_again_with_the_new_one() -> None:
    harness = _harness(Answer(401, _error(401, "unauthorized", "expired")), Answer(200, BOT))

    harness.api.me()

    assert (harness.tokens.renewals, [sent.authorization for sent in harness.notion.sent]) == (
        1,
        ["Bearer first-token", "Bearer second-token"],
    )


def test_a_token_refused_after_a_second_renewal_stops_with_advice_to_sign_in_again() -> None:
    refused = Answer(401, _error(401, "unauthorized", "expired"))
    harness = _harness(refused, refused, refused)

    with pytest.raises(AuthError) as caught:
        harness.api.me()

    assert (str(caught.value), harness.tokens.renewals) == (
        "Notion refused the renewed sign-in; run `skaldr auth notion` again",
        2,
    )
    assert "third-token" not in rendered_traceback(caught.value)


def test_a_request_refused_once_after_renewal_is_sent_again_after_a_second() -> None:
    refused = Answer(401, _error(401, "unauthorized", "expired"))
    harness = _harness(refused, refused, Answer(200, BOT))

    harness.api.me()

    assert [sent.authorization for sent in harness.notion.sent] == [
        "Bearer first-token",
        "Bearer second-token",
        "Bearer third-token",
    ]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        pytest.param(400, "validation_error", id="invalid"),
        pytest.param(403, "restricted_resource", id="forbidden"),
    ],
)
def test_a_refused_read_is_a_connector_error_not_a_rejected_write(status: int, code: str) -> None:
    harness = _harness(Answer(status, _error(status, code, "no")))

    with pytest.raises(ConnectorError) as caught:
        harness.api.page_markdown(PAGE_ID)

    assert (type(caught.value), str(caught.value)) == (
        ConnectorError,
        f"Notion could not read the content of page {PAGE_ID}: HTTP {status} {code}: no",
    )


@pytest.mark.parametrize(
    ("status", "code"),
    [
        pytest.param(400, "validation_error", id="invalid"),
        pytest.param(403, "restricted_resource", id="forbidden"),
        pytest.param(409, "conflict_error", id="conflict"),
    ],
)
def test_a_refused_write_is_a_rejected_write(status: int, code: str) -> None:
    harness = _harness(Answer(status, _error(status, code, "no")))

    with pytest.raises(WriteRejectedError, match=rf"^Notion refused to create a page: no \({code}\)$"):
        harness.api.create_page({"parent": {"page_id": PAGE_ID}})


def test_a_missing_page_is_an_item_not_found_error() -> None:
    harness = _harness(Answer(404, _error(404, "object_not_found", "Could not find page")))

    with pytest.raises(
        ItemNotFoundError,
        match=rf"^Notion could not read page {PAGE_ID}: it has no such object, or this sign-in cannot see "
        r"it$",
    ):
        harness.api.page(PAGE_ID)


def test_an_unreachable_notion_is_a_connector_error_that_names_no_token() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    api = NotionApi(CountingTokens(iter([])), transport=httpx2.MockTransport(refuse), sleep=lambda _: None)

    with pytest.raises(ConnectorError) as caught:
        api.me()

    assert (str(caught.value), "first-token" in rendered_traceback(caught.value)) == (
        "Notion could not read the signed-in bot: could not reach Notion (connection refused)",
        False,
    )


def test_an_answer_of_an_unexpected_shape_names_the_fields() -> None:
    harness = _harness(Answer(200, {"object": "page", "id": PAGE_ID}))

    with pytest.raises(
        ConnectorError,
        match=re.escape(
            f"Notion answered an unexpected shape to read page {PAGE_ID}: "
            "last_edited_time, last_edited_by, in_trash, properties"
        ),
    ):
        harness.api.page(PAGE_ID)


def test_a_markdown_read_reports_a_page_notion_cut_short() -> None:
    harness = _harness(Answer(200, {**MARKDOWN, "truncated": True}))

    with pytest.raises(
        ConnectorError,
        match=rf"^Notion sent only part of page {PAGE_ID}, which is too large to read whole; split the "
        r"document further with `split`$",
    ):
        harness.api.page_markdown(PAGE_ID)


UNFOLLOWED = (
    "Notion accepted the request to create a page as task task-1 but skaldr could not follow it: {}; the "
    "change may still land, so read the page before publishing again"
)


@pytest.mark.parametrize(
    ("polled", "cause"),
    [
        pytest.param(
            [Answer(404, _error(404, "object_not_found", "gone"))],
            "Notion could not read the progress of task task-1: it has no such object, or this sign-in "
            "cannot see it",
            id="task-gone",
        ),
        pytest.param(
            [Answer(401, _error(401, "unauthorized", "expired"))] * 3,
            "Notion refused the renewed sign-in; run `skaldr auth notion` again",
            id="sign-in-refused",
        ),
        pytest.param(
            [_failing(httpx2.ReadTimeout)] * 6,
            "Notion could not read the progress of task task-1: could not reach Notion (timed out)",
            id="unreachable",
        ),
    ],
)
def test_a_failure_while_following_an_accepted_task_says_the_change_may_still_land(
    polled: list[Answer], cause: str
) -> None:
    harness = _harness(Answer(202, _task("queued", poll_after_seconds=1)), *polled)

    with pytest.raises(ConnectorError) as caught:
        harness.api.create_page({"parent": {"page_id": PAGE_ID}})

    assert (type(caught.value), str(caught.value)) == (ConnectorError, UNFOLLOWED.format(cause))


def test_a_read_that_cannot_reach_notion_is_tried_again() -> None:
    harness = _harness(_failing(httpx2.ConnectError), _failing(httpx2.ReadTimeout), Answer(200, BOT))

    harness.api.me()

    assert (len(harness.notion.sent), harness.sleeps) == (3, [1.0, 2.0])


def test_a_write_whose_answer_never_arrived_is_not_tried_again_because_it_may_have_landed() -> None:
    harness = _harness(_failing(httpx2.ReadTimeout))

    with pytest.raises(ConnectorError) as caught:
        harness.api.update_page(PAGE_ID, {"in_trash": True})

    assert (type(caught.value), str(caught.value), len(harness.notion.sent)) == (
        ConnectorError,
        f"Notion could not change page {PAGE_ID}: no answer arrived (timed out); the change may have landed, "
        "so read the page before publishing again",
        1,
    )


def test_a_write_that_never_reached_notion_says_so() -> None:
    harness = _harness(_failing(httpx2.ConnectError))

    with pytest.raises(
        ConnectorError, match=rf"^Notion could not change page {PAGE_ID}: could not reach Notion \(reset\)$"
    ):
        harness.api.update_page(PAGE_ID, {"in_trash": True})
    assert len(harness.notion.sent) == 1


@pytest.mark.parametrize(
    ("call", "refusal"),
    [
        pytest.param(
            "write",
            WriteRejectedError(
                f"Notion asked skaldr to wait 120 seconds before it may change page {PAGE_ID}, longer than "
                "the 60 seconds skaldr waits; publish again later"
            ),
            id="write",
        ),
        pytest.param(
            "read",
            ConnectorError(
                "Notion asked skaldr to wait 120 seconds before it may read the signed-in bot, longer than "
                "the 60 seconds skaldr waits; publish again later"
            ),
            id="read",
        ),
    ],
)
def test_a_retry_after_longer_than_a_minute_is_not_waited_for(call: str, refusal: ConnectorError) -> None:
    harness = _harness(Answer(429, _error(429, "rate_limited", "slow down"), {"Retry-After": "120"}))

    with pytest.raises(ConnectorError) as caught:
        if call == "write":
            harness.api.update_page(PAGE_ID, {"in_trash": True})
        else:
            harness.api.me()

    assert (type(caught.value), str(caught.value), harness.sleeps) == (type(refusal), str(refusal), [])
