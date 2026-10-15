from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.slack.api import SlackApi
from skaldr.publish_block.target import JsonFields
from tests.factories.auth_factory import SLACK_USER_TOKEN
from tests.factories.slack_factory import FakeToken, form_fields

CANVAS = "F0EXAMPLE1"
Answer = tuple[int, Any] | tuple[int, Any, dict[str, str]] | Exception


class Scripted:
    def __init__(self, *answers: Answer) -> None:
        self.answers = list(answers)
        self.requests: list[httpx2.Request] = []
        self.slept: list[float] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body, *headers = answer
        if isinstance(body, bytes):
            return httpx2.Response(status, content=body, headers=headers[0] if headers else None)
        return httpx2.Response(status, json=body, headers=headers[0] if headers else None)

    def api(self) -> SlackApi:
        return SlackApi(FakeToken(), transport=httpx2.MockTransport(self.handle), sleep=self.slept.append)

    def sent(self) -> list[tuple[str, str, str | None, dict[str, Any]]]:
        return [
            (request.method, str(request.url), request.headers.get("authorization"), form_fields(request))
            for request in self.requests
        ]


OK: Answer = (200, {"ok": True})


def _refused(code: str, **more: str) -> Answer:
    return (200, {"ok": False, "error": code, **more})


def test_creating_a_canvas_sends_its_title_and_markdown_and_returns_its_id() -> None:
    slack = Scripted((200, {"ok": True, "canvas_id": CANVAS}))

    canvas_id = slack.api().create_canvas("Garden handbook", "Welcome.\n")

    assert (canvas_id, slack.sent()) == (
        CANVAS,
        [
            (
                "POST",
                "https://slack.com/api/canvases.create",
                f"Bearer {SLACK_USER_TOKEN}",
                {
                    "title": "Garden handbook",
                    "document_content": {"type": "markdown", "markdown": "Welcome.\n"},
                },
            )
        ],
    )


def test_an_edit_sends_its_one_change() -> None:
    slack = Scripted(OK)
    change: JsonFields = {"operation": "delete", "section_id": "temp:C:1"}

    slack.api().edit_canvas(CANVAS, change)

    assert slack.sent() == [
        (
            "POST",
            "https://slack.com/api/canvases.edit",
            f"Bearer {SLACK_USER_TOKEN}",
            {"canvas_id": CANVAS, "changes": [change]},
        )
    ]


@pytest.mark.parametrize(
    ("read", "content_type"),
    [
        pytest.param(SlackApi.canvas_markdown, "markdown", id="markdown"),
        pytest.param(SlackApi.canvas_html, "html", id="html"),
    ],
)
def test_reading_a_canvas_asks_for_its_content_in_one_form(
    read: Callable[[SlackApi, str], str], content_type: str
) -> None:
    slack = Scripted((200, {"ok": True, "content": "# Garden handbook\n"}))

    content = read(slack.api(), CANVAS)

    assert (content, [(url, form) for _, url, _, form in slack.sent()]) == (
        "# Garden handbook\n",
        [
            (
                "https://slack.com/api/canvases.getContent",
                {"canvas_id": CANVAS, "content_type": content_type},
            )
        ],
    )


def test_a_message_is_posted_to_the_conversation() -> None:
    slack = Scripted(OK)

    slack.api().post_message("C0EXAMPLE1", "Garden handbook: https://example.slack.com/docs/T0EXAMPLE1/F0")

    assert [(url, form) for _, url, _, form in slack.sent()] == [
        (
            "https://slack.com/api/chat.postMessage",
            {
                "channel": "C0EXAMPLE1",
                "text": "Garden handbook: https://example.slack.com/docs/T0EXAMPLE1/F0",
            },
        )
    ]


def test_the_signed_in_workspace_is_asked_for_once() -> None:
    slack = Scripted((200, {"ok": True, "url": "https://example.slack.com/", "team_id": "T0EXAMPLE1"}))
    api = slack.api()

    first, second = api.signed_in_as(), api.signed_in_as()

    assert ((first.url, first.team_id), first == second, len(slack.requests)) == (
        ("https://example.slack.com/", "T0EXAMPLE1"),
        True,
        1,
    )


def test_too_many_requests_waits_as_long_as_slack_asks_then_retries() -> None:
    slack = Scripted((429, {"ok": False, "error": "ratelimited"}, {"Retry-After": "3"}), OK)

    slack.api().edit_canvas(CANVAS, {"operation": "insert_at_end"})

    assert (slack.slept, len(slack.requests)) == ([3.0], 2)


def test_a_wait_longer_than_a_minute_is_not_waited_out() -> None:
    slack = Scripted((429, {"ok": False, "error": "ratelimited"}, {"Retry-After": "120"}))

    with pytest.raises(WriteRejectedError) as raised:
        slack.api().edit_canvas(CANVAS, {"operation": "insert_at_end"})

    assert (str(raised.value), slack.slept) == (
        f"Slack asked skaldr to wait 120 seconds before it may change canvas {CANVAS}, longer than the 60 "
        "seconds skaldr waits; publish again later",
        [],
    )


def test_a_locked_canvas_is_tried_again_after_a_growing_pause() -> None:
    locked = _refused("canvas_editing_locked")
    slack = Scripted(locked, locked, OK)

    slack.api().edit_canvas(CANVAS, {"operation": "insert_at_end"})

    assert (slack.slept, len(slack.requests)) == ([1.0, 2.0], 3)


def test_a_canvas_that_stays_locked_is_refused_after_five_attempts() -> None:
    slack = Scripted(*[_refused("canvas_editing_locked")] * 5)

    with pytest.raises(WriteRejectedError) as raised:
        slack.api().edit_canvas(CANVAS, {"operation": "insert_at_end"})

    assert (str(raised.value), len(slack.requests)) == (
        f"Slack could not change canvas {CANVAS}: someone is editing it (canvas_editing_locked) after 5 "
        "attempts; publish again in a moment",
        5,
    )


def test_too_many_requests_after_five_attempts_is_refused() -> None:
    slack = Scripted(*[(429, {"ok": False, "error": "ratelimited"})] * 5)

    with pytest.raises(ConnectorError) as raised:
        slack.api().canvas_markdown(CANVAS)

    assert (type(raised.value), str(raised.value)) == (
        ConnectorError,
        f"Slack kept refusing to read canvas {CANVAS} as too many requests after 5 attempts; publish again "
        "in a minute",
    )


def test_a_server_error_is_retried_on_a_read() -> None:
    slack = Scripted((503, b"busy"), (200, {"ok": True, "content": ""}))

    assert (slack.api().canvas_markdown(CANVAS), len(slack.requests)) == ("", 2)


def test_a_server_error_is_not_retried_on_a_write() -> None:
    slack = Scripted((503, b"busy"))

    with pytest.raises(ConnectorError) as raised:
        slack.api().edit_canvas(CANVAS, {"operation": "insert_at_end"})

    assert (type(raised.value), str(raised.value), len(slack.requests)) == (
        ConnectorError,
        f"Slack answered HTTP 503 when asked to change canvas {CANVAS}",
        1,
    )


def test_a_dropped_read_is_retried() -> None:
    slack = Scripted(httpx2.ReadTimeout("timed out"), (200, {"ok": True, "content": "x\n"}))

    assert slack.api().canvas_markdown(CANVAS) == "x\n"


def test_an_unreachable_slack_on_a_read_is_named_after_the_last_attempt() -> None:
    slack = Scripted(*[httpx2.ConnectError("connection refused")] * 5)

    with pytest.raises(ConnectorError) as raised:
        slack.api().canvas_markdown(CANVAS)

    assert str(raised.value) == (
        f"Slack could not read canvas {CANVAS}: could not reach Slack (connection refused)"
    )


def test_an_edit_that_got_no_answer_may_have_landed() -> None:
    slack = Scripted(httpx2.ReadTimeout("timed out"))

    with pytest.raises(ConnectorError) as raised:
        slack.api().edit_canvas(CANVAS, {"operation": "insert_at_end"})

    assert (type(raised.value), str(raised.value), len(slack.requests)) == (
        ConnectorError,
        f"Slack could not change canvas {CANVAS}: no answer arrived (timed out); the change may have landed, "
        "so read the canvas before publishing again",
        1,
    )


def test_a_create_that_got_no_answer_may_have_made_a_canvas_with_that_title() -> None:
    slack = Scripted(httpx2.ReadTimeout("timed out"))

    with pytest.raises(ConnectorError) as raised:
        slack.api().create_canvas("Garden handbook", "Welcome.\n")

    assert (type(raised.value), str(raised.value), len(slack.requests)) == (
        ConnectorError,
        'Slack could not create a canvas: no answer arrived (timed out); a canvas titled "Garden handbook" '
        "may exist already, so look for it in Slack before publishing again",
        1,
    )


def test_a_conversation_is_given_read_access_to_a_canvas() -> None:
    slack = Scripted(OK)

    slack.api().let_read(CANVAS, "C0EXAMPLE1")

    assert [(url, form) for _, url, _, form in slack.sent()] == [
        (
            "https://slack.com/api/canvases.access.set",
            {"canvas_id": CANVAS, "access_level": "read", "channel_ids": ["C0EXAMPLE1"]},
        )
    ]


def _post(api: SlackApi) -> None:
    api.post_message("C0EXAMPLE1", "Garden handbook")


def _change(api: SlackApi) -> None:
    api.edit_canvas(CANVAS, {"operation": "insert_at_end"})


def _read(api: SlackApi) -> None:
    api.canvas_markdown(CANVAS)


@pytest.mark.parametrize(
    ("call", "answer", "error", "message"),
    [
        pytest.param(
            _read,
            _refused("canvas_not_found"),
            ItemNotFoundError,
            f"Slack could not read canvas {CANVAS}: the canvas is gone or this sign-in cannot see it "
            "(canvas_not_found)",
            id="not-found",
        ),
        pytest.param(
            _change,
            _refused("canvas_deleted"),
            ItemNotFoundError,
            f"Slack could not change canvas {CANVAS}: the canvas is gone or this sign-in cannot see it "
            "(canvas_deleted)",
            id="deleted",
        ),
        pytest.param(
            _read,
            _refused("token_revoked"),
            ConnectorError,
            f"Slack rejected the sign-in when asked to read canvas {CANVAS} (token_revoked); run "
            "`skaldr auth slack` with a new user token",
            id="revoked-on-a-read",
        ),
        pytest.param(
            _read,
            _refused("token_expired"),
            ConnectorError,
            f"Slack rejected the sign-in when asked to read canvas {CANVAS} (token_expired); run "
            "`skaldr auth slack` with a new user token. A rotating token (xoxe.xoxp-...) expires and skaldr "
            "does not renew it, so it is not supported: use an app that does not rotate its tokens",
            id="expired",
        ),
        pytest.param(
            _change,
            _refused("invalid_auth"),
            WriteRejectedError,
            f"Slack rejected the sign-in when asked to change canvas {CANVAS} (invalid_auth); run "
            "`skaldr auth slack` with a new user token",
            id="invalid-on-a-write",
        ),
        pytest.param(
            _change,
            _refused("missing_scope", needed="canvases:write"),
            WriteRejectedError,
            f"Slack could not change canvas {CANVAS}: the user token lacks the scope canvases:write; add it "
            "to your Slack app under OAuth & Permissions, reinstall the app, and run `skaldr auth slack` "
            "again",
            id="missing-scope",
        ),
        pytest.param(
            _change,
            _refused("canvas_too_large"),
            WriteRejectedError,
            f"Slack could not change canvas {CANVAS}: the canvas would be larger than Slack allows "
            "(canvas_too_large); split the document further with `split`, or shorten it",
            id="too-large",
        ),
        pytest.param(
            _change,
            _refused("free_teams_cannot_edit_standalone_canvases"),
            WriteRejectedError,
            f"Slack could not change canvas {CANVAS}: a workspace on Slack's free plan cannot edit a "
            "standalone canvas (free_teams_cannot_edit_standalone_canvases)",
            id="free-plan",
        ),
        pytest.param(
            _change,
            _refused("canvas_disabled_user_team"),
            WriteRejectedError,
            f"Slack refused to change canvas {CANVAS} (canvas_disabled_user_team)",
            id="other-write-refusal",
        ),
        pytest.param(
            _read,
            _refused("\x1b[2Jodd"),
            ConnectorError,
            f"Slack refused to read canvas {CANVAS} ([2Jodd)",
            id="other-read-refusal-shown-printable",
        ),
        pytest.param(
            _read,
            (200, b"<html>busy</html>"),
            ConnectorError,
            f"Slack answered with something that is not JSON when asked to read canvas {CANVAS}",
            id="not-json",
        ),
        pytest.param(
            _read,
            (200, {"ok": True}),
            ConnectorError,
            f"Slack answered an unexpected shape when asked to read canvas {CANVAS}: content",
            id="unexpected-shape",
        ),
        pytest.param(
            _change,
            (404, b"no such method"),
            WriteRejectedError,
            f"Slack answered HTTP 404 when asked to change canvas {CANVAS}",
            id="http-error-on-a-write",
        ),
        pytest.param(
            _post,
            _refused("channel_not_found"),
            WriteRejectedError,
            "Slack could not post the canvas link in C0EXAMPLE1: Slack has no such conversation, or this "
            "sign-in cannot see it (channel_not_found)",
            id="no-such-conversation",
        ),
        pytest.param(
            _post,
            _refused("not_in_channel"),
            WriteRejectedError,
            "Slack could not post the canvas link in C0EXAMPLE1: you are not a member of the conversation; "
            "join it, or name another (not_in_channel)",
            id="not-a-member",
        ),
        pytest.param(
            _post,
            _refused("is_archived"),
            WriteRejectedError,
            "Slack could not post the canvas link in C0EXAMPLE1: the conversation is archived (is_archived)",
            id="archived-conversation",
        ),
    ],
)
def test_each_slack_error_is_named(
    call: Callable[[SlackApi], None], answer: Answer, error: type[ConnectorError], message: str
) -> None:
    with pytest.raises(ConnectorError) as raised:
        call(Scripted(answer).api())

    assert (type(raised.value), str(raised.value)) == (error, message)
