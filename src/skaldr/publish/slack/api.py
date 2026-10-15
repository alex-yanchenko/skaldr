import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Final, Protocol, TypeVar

import httpx2
from pydantic import JsonValue, ValidationError
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from skaldr.auth import HTTP_TIMEOUT_SECONDS, printable_only
from skaldr.auth.slack import REJECTED_SIGN_IN_ERRORS, SLACK_API
from skaldr.auth.store import SLACK_ROTATING_TOKENS
from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.connector import SPLIT_ADVICE
from skaldr.publish.slack.responses import CanvasContent, CreatedCanvas, Identity, SlackResponse
from skaldr.publish_block.target import JsonFields

Sleep = Callable[[float], None]
Answer = TypeVar("Answer", bound=SlackResponse)

RETRY_ATTEMPTS: Final = 5
LONGEST_BACKOFF_SECONDS: Final = 30.0
LONGEST_RETRY_AFTER_SECONDS: Final = 60.0
EDITING_LOCKED: Final = "canvas_editing_locked"
RATE_LIMITED: Final = "ratelimited"
MISSING_SCOPE: Final = "missing_scope"
TOKEN_EXPIRED: Final = "token_expired"
MISSING_CANVAS_ERRORS: Final = frozenset({"canvas_not_found", "canvas_deleted"})
_BACKOFF: Final = wait_exponential(multiplier=1, max=LONGEST_BACKOFF_SECONDS)


class TokenSource(Protocol):
    @property
    def access_token(self) -> str: ...


CHANGE_MAY_HAVE_LANDED: Final = "the change may have landed, so read the canvas before publishing again"
CONVERSATION_REFUSALS: Final = {
    "channel_not_found": "Slack has no such conversation, or this sign-in cannot see it",
    "not_in_channel": "you are not a member of the conversation; join it, or name another",
    "is_archived": "the conversation is archived",
}


@dataclass(frozen=True)
class _Call:
    method: str
    to_do: str
    writes: bool
    if_unanswered: str = CHANGE_MAY_HAVE_LANDED


def markdown_content(markdown: str) -> JsonFields:
    return {"type": "markdown", "markdown": markdown}


def _form_value(value: JsonValue) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _retry_after_seconds(response: httpx2.Response) -> float | None:
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _error_code(response: httpx2.Response) -> str | None:
    try:
        return SlackResponse.model_validate_json(response.content).error
    except ValidationError:
        return None


def _is_rate_limited(response: httpx2.Response) -> bool:
    return response.status_code == HTTPStatus.TOO_MANY_REQUESTS or _error_code(response) == RATE_LIMITED


def _asks_for_too_long_a_wait(response: httpx2.Response) -> float | None:
    told = _retry_after_seconds(response)
    too_long = _is_rate_limited(response) and told is not None and told > LONGEST_RETRY_AFTER_SECONDS
    return told if too_long else None


def _worth_retrying(call: _Call) -> Callable[[httpx2.Response], bool]:
    def worth(response: httpx2.Response) -> bool:
        if _asks_for_too_long_a_wait(response) is not None:
            return False
        if _is_rate_limited(response) or _error_code(response) == EDITING_LOCKED:
            return True
        return not call.writes and response.is_server_error

    return worth


def _dropped_read(call: _Call) -> Callable[[BaseException], bool]:
    def dropped(error: BaseException) -> bool:
        return not call.writes and isinstance(error, httpx2.TransportError)

    return dropped


def _last_answer(state: RetryCallState) -> httpx2.Response:
    if state.outcome is None:
        raise AssertionError("tenacity gave up before any attempt")
    answer: httpx2.Response = state.outcome.result()
    return answer


def _wait(state: RetryCallState) -> float:
    outcome = state.outcome
    if outcome is None or outcome.failed:
        return _BACKOFF(state)
    told = _retry_after_seconds(outcome.result())
    return told if told is not None else _BACKOFF(state)


def _refusal_class(call: _Call) -> type[ConnectorError]:
    return WriteRejectedError if call.writes else ConnectorError


def _slack_refusal(call: _Call, body: SlackResponse, attempts: int) -> ConnectorError:
    code = printable_only(body.error or "no error named")
    if code in MISSING_CANVAS_ERRORS:
        return ItemNotFoundError(
            f"Slack could not {call.to_do}: the canvas is gone or this sign-in cannot see it ({code})"
        )
    if code in REJECTED_SIGN_IN_ERRORS:
        rotating = f". {SLACK_ROTATING_TOKENS}" if code == TOKEN_EXPIRED else ""
        return _refusal_class(call)(
            f"Slack rejected the sign-in when asked to {call.to_do} ({code}); run `skaldr auth slack` with a "
            f"new user token{rotating}"
        )
    if code == MISSING_SCOPE:
        scope = printable_only(body.needed or "")
        return _refusal_class(call)(
            f"Slack could not {call.to_do}: the user token lacks the scope {scope}; add it to your Slack app "
            "under OAuth & Permissions, reinstall the app, and run `skaldr auth slack` again"
        )
    if code == EDITING_LOCKED:
        return WriteRejectedError(
            f"Slack could not {call.to_do}: someone is editing it ({code}) after {attempts} attempts; "
            "publish again in a moment"
        )
    if code == "canvas_too_large":
        return WriteRejectedError(
            f"Slack could not {call.to_do}: the canvas would be larger than Slack allows ({code}); "
            f"{SPLIT_ADVICE}"
        )
    if code in CONVERSATION_REFUSALS:
        return WriteRejectedError(f"Slack could not {call.to_do}: {CONVERSATION_REFUSALS[code]} ({code})")
    if code == "free_teams_cannot_edit_standalone_canvases":
        return WriteRejectedError(
            f"Slack could not {call.to_do}: a workspace on Slack's free plan cannot edit a standalone canvas "
            f"({code})"
        )
    return _refusal_class(call)(f"Slack refused to {call.to_do} ({code})")


def _failure(call: _Call, response: httpx2.Response, attempts: int) -> ConnectorError | None:
    wait = _asks_for_too_long_a_wait(response)
    if wait is not None:
        return _refusal_class(call)(
            f"Slack asked skaldr to wait {wait:g} seconds before it may {call.to_do}, longer than the "
            f"{LONGEST_RETRY_AFTER_SECONDS:g} seconds skaldr waits; publish again later"
        )
    if _is_rate_limited(response):
        return _refusal_class(call)(
            f"Slack kept refusing to {call.to_do} as too many requests after {attempts} attempts; publish "
            "again in a minute"
        )
    if response.is_server_error:
        return ConnectorError(f"Slack answered HTTP {response.status_code} when asked to {call.to_do}")
    if response.status_code != HTTPStatus.OK:
        return _refusal_class(call)(f"Slack answered HTTP {response.status_code} when asked to {call.to_do}")
    try:
        body = SlackResponse.model_validate_json(response.content)
    except ValidationError:
        return ConnectorError(f"Slack answered with something that is not JSON when asked to {call.to_do}")
    return None if body.ok else _slack_refusal(call, body, attempts)


class SlackApi:
    def __init__(
        self, tokens: TokenSource, *, transport: httpx2.BaseTransport | None = None, sleep: Sleep = time.sleep
    ) -> None:
        self._tokens = tokens
        self._sleep = sleep
        self._client = httpx2.Client(base_url=SLACK_API, transport=transport, timeout=HTTP_TIMEOUT_SECONDS)
        self._identity: Identity | None = None

    def close(self) -> None:
        self._client.close()

    def signed_in_as(self) -> Identity:
        if self._identity is None:
            call = _Call("auth.test", "read which workspace this sign-in belongs to", writes=False)
            self._identity = self._answer(Identity, call, {})
        return self._identity

    def create_canvas(self, title: str, markdown: str) -> str:
        landed = f'a canvas titled "{title}" may exist already, so look for it in Slack before publishing'
        call = _Call("canvases.create", "create a canvas", writes=True, if_unanswered=f"{landed} again")
        arguments: JsonFields = {"title": title, "document_content": markdown_content(markdown)}
        return self._answer(CreatedCanvas, call, arguments).canvas_id

    def let_read(self, canvas_id: str, conversation: str) -> None:
        call = _Call("canvases.access.set", f"let {conversation} read canvas {canvas_id}", writes=True)
        arguments: JsonFields = {
            "canvas_id": canvas_id,
            "access_level": "read",
            "channel_ids": [conversation],
        }
        self._answer(SlackResponse, call, arguments)

    def edit_canvas(self, canvas_id: str, change: JsonFields) -> None:
        call = _Call("canvases.edit", f"change canvas {canvas_id}", writes=True)
        self._answer(SlackResponse, call, {"canvas_id": canvas_id, "changes": [change]})

    def canvas_markdown(self, canvas_id: str) -> str:
        call = _Call("canvases.getContent", f"read canvas {canvas_id}", writes=False)
        arguments: JsonFields = {"canvas_id": canvas_id, "content_type": "markdown"}
        return self._answer(CanvasContent, call, arguments).content

    def post_message(self, channel: str, text: str) -> None:
        call = _Call("chat.postMessage", f"post the canvas link in {channel}", writes=True)
        self._answer(SlackResponse, call, {"channel": channel, "text": text})

    def _answer(self, shape: type[Answer], call: _Call, arguments: Mapping[str, JsonValue]) -> Answer:
        retrying = Retrying(
            stop=stop_after_attempt(RETRY_ATTEMPTS),
            wait=_wait,
            retry=retry_if_result(_worth_retrying(call)) | retry_if_exception(_dropped_read(call)),
            sleep=self._sleep,
            retry_error_callback=_last_answer,
        )
        try:
            response: httpx2.Response = retrying(self._request, call, arguments)
        except httpx2.TransportError as exc:
            if call.writes:
                raise ConnectorError(
                    f"Slack could not {call.to_do}: no answer arrived ({exc}); {call.if_unanswered}"
                ) from None
            raise ConnectorError(f"Slack could not {call.to_do}: could not reach Slack ({exc})") from None
        failure = _failure(call, response, retrying.statistics["attempt_number"])
        if failure is not None:
            raise failure
        try:
            return shape.model_validate_json(response.content)
        except ValidationError as exc:
            fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors(include_input=False))
            raise ConnectorError(
                f"Slack answered an unexpected shape when asked to {call.to_do}: {fields}"
            ) from None

    def _request(self, call: _Call, arguments: Mapping[str, JsonValue]) -> httpx2.Response:
        return self._client.post(
            f"/{call.method}",
            data={name: _form_value(value) for name, value in arguments.items()},
            headers={"Authorization": f"Bearer {self._tokens.access_token}"},
        )
