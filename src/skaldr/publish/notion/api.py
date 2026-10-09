import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Final, Protocol, TypeVar

import httpx2
from pydantic import JsonValue, TypeAdapter, ValidationError
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from skaldr.auth import HTTP_TIMEOUT_SECONDS, printable_only
from skaldr.errors import AuthError, ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.notion.responses import (
    AsyncTask,
    Block,
    Database,
    DataSource,
    ErrorBody,
    FailedTask,
    Page,
    PageMarkdown,
    PendingTask,
    SucceededTask,
    User,
)
from skaldr.publish_block.target import JsonFields

NOTION_API: Final = "https://api.notion.com"
NOTION_VERSION: Final = "2026-03-11"
RETRY_ATTEMPTS: Final = 6
LONGEST_BACKOFF_SECONDS: Final = 30.0
SHORTEST_POLL_SECONDS: Final = 0.5
LONGEST_TASK_WAIT_SECONDS: Final = 600.0
LONGEST_RETRY_AFTER_SECONDS: Final = 60.0
NOT_SENT: Final = (httpx2.ConnectError, httpx2.ConnectTimeout)
ALWAYS_RETRIED: Final = frozenset({HTTPStatus.TOO_MANY_REQUESTS, 529})
REFUSED_WRITE_STATUSES: Final = frozenset(
    {HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN, HTTPStatus.CONFLICT, HTTPStatus.TOO_MANY_REQUESTS}
)
SIGN_IN_AGAIN: Final = "; run `skaldr auth notion` again"

Answer = TypeVar("Answer")
Sleep = Callable[[float], None]


class TokenSource(Protocol):
    @property
    def access_token(self) -> str: ...

    def renew(self) -> None: ...


@dataclass(frozen=True)
class _Action:
    to_do: str
    doing: str
    writes: bool


def _retry_after_seconds(response: httpx2.Response) -> float | None:
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


_BACKOFF = wait_exponential(multiplier=1, max=LONGEST_BACKOFF_SECONDS)


class _UnreachableError(ConnectorError):
    pass


def _wait_before_retrying(state: RetryCallState) -> float:
    outcome = state.outcome
    response = None if outcome is None or outcome.failed else outcome.result()
    told = _retry_after_seconds(response) if isinstance(response, httpx2.Response) else None
    return told if told is not None else _BACKOFF(state)


def _last_answer(state: RetryCallState) -> httpx2.Response:
    if state.outcome is None:
        raise AssertionError("tenacity gave up before any attempt")
    answer: httpx2.Response = state.outcome.result()
    return answer


def _asks_for_too_long_a_wait(response: httpx2.Response) -> float | None:
    told = _retry_after_seconds(response)
    too_long = (
        response.status_code in ALWAYS_RETRIED and told is not None and told > LONGEST_RETRY_AFTER_SECONDS
    )
    return told if too_long else None


def _deserves_a_retry(method: str) -> Callable[[httpx2.Response], bool]:
    def deserves(response: httpx2.Response) -> bool:
        status = response.status_code
        server_error = HTTPStatus.INTERNAL_SERVER_ERROR <= status < 600
        if _asks_for_too_long_a_wait(response) is not None:
            return False
        return status in ALWAYS_RETRIED or (server_error and method == "GET")

    return deserves


def _unreachable_on_a_read(method: str) -> Callable[[BaseException], bool]:
    def unreachable(exc: BaseException) -> bool:
        return method == "GET" and isinstance(exc, _UnreachableError)

    return unreachable


def _error_body(response: httpx2.Response) -> ErrorBody:
    try:
        return ErrorBody.model_validate(response.json())
    except (json.JSONDecodeError, ValidationError):
        return ErrorBody()


def notion_failure(status: int, error: ErrorBody, action: _Action) -> ConnectorError:
    message = printable_only(error.message)
    code = printable_only(error.code)
    if status == HTTPStatus.NOT_FOUND:
        return ItemNotFoundError(
            f"Notion could not {action.to_do}: it has no such object, or this sign-in cannot see it"
        )
    if action.writes and status in REFUSED_WRITE_STATUSES:
        return WriteRejectedError(f"Notion refused to {action.to_do}: {message} ({code})")
    return ConnectorError(f"Notion could not {action.to_do}: HTTP {status} {code}: {message}")


def _validated(shape: type[Answer] | TypeAdapter[Answer], data: object, action: _Action) -> Answer:
    adapter = shape if isinstance(shape, TypeAdapter) else TypeAdapter(shape)
    try:
        return adapter.validate_python(data)
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors(include_input=False))
        raise ConnectorError(f"Notion answered an unexpected shape to {action.to_do}: {fields}") from None


_ASYNC_TASK: Final = TypeAdapter[PendingTask | SucceededTask | FailedTask](AsyncTask)


class NotionApi:
    def __init__(
        self,
        tokens: TokenSource,
        *,
        transport: httpx2.BaseTransport | None = None,
        sleep: Sleep = time.sleep,
    ) -> None:
        self._tokens = tokens
        self._sleep = sleep
        self._client = httpx2.Client(base_url=NOTION_API, transport=transport, timeout=HTTP_TIMEOUT_SECONDS)

    def close(self) -> None:
        self._client.close()

    def me(self) -> User:
        return self._get(User, "/v1/users/me", _Action("read the signed-in bot", "reading", writes=False))

    def page(self, page_id: str) -> Page:
        return self._get(
            Page, f"/v1/pages/{page_id}", _Action(f"read page {page_id}", "reading", writes=False)
        )

    def page_markdown(self, page_id: str) -> PageMarkdown:
        action = _Action(f"read the content of page {page_id}", "reading", writes=False)
        markdown = self._get(PageMarkdown, f"/v1/pages/{page_id}/markdown", action)
        if markdown.truncated:
            raise ConnectorError(
                f"Notion sent only part of page {page_id}, which is too large to read whole; split the "
                "document further with `split`"
            )
        return markdown

    def block(self, block_id: str) -> Block:
        return self._get(Block, f"/v1/blocks/{block_id}", _Action(f"read block {block_id}", "reading", False))

    def database(self, database_id: str) -> Database:
        action = _Action(f"read database {database_id}", "reading", writes=False)
        return self._get(Database, f"/v1/databases/{database_id}", action)

    def data_source(self, data_source_id: str) -> DataSource:
        action = _Action(f"read data source {data_source_id}", "reading", writes=False)
        return self._get(DataSource, f"/v1/data_sources/{data_source_id}", action)

    def create_page(self, body: JsonFields) -> Page:
        action = _Action("create a page", "creating a page", writes=True)
        answer = self._send("POST", "/v1/pages", {**body, "allow_async": True}, action)
        return _validated(Page, self._finished(answer, action), action)

    def update_page(self, page_id: str, body: JsonFields) -> Page:
        action = _Action(f"change page {page_id}", f"changing page {page_id}", writes=True)
        answer = self._send("PATCH", f"/v1/pages/{page_id}", body, action)
        return _validated(Page, self._succeeded(answer, action), action)

    def update_markdown(self, page_id: str, command: JsonFields) -> PageMarkdown:
        action = _Action(
            f"change the content of page {page_id}", f"changing the content of page {page_id}", writes=True
        )
        answer = self._send(
            "PATCH", f"/v1/pages/{page_id}/markdown", {**command, "allow_async": True}, action
        )
        return _validated(PageMarkdown, self._finished(answer, action), action)

    def _get(self, shape: type[Answer], path: str, action: _Action) -> Answer:
        return _validated(shape, self._succeeded(self._send("GET", path, None, action), action), action)

    def _succeeded(self, answer: httpx2.Response, action: _Action) -> object:
        wait = _asks_for_too_long_a_wait(answer)
        if wait is not None:
            refused = action.writes and answer.status_code == HTTPStatus.TOO_MANY_REQUESTS
            raise (WriteRejectedError if refused else ConnectorError)(
                f"Notion asked skaldr to wait {wait:g} seconds before it may {action.to_do}, longer than the "
                f"{LONGEST_RETRY_AFTER_SECONDS:g} seconds skaldr waits; publish again later"
            )
        if not answer.is_success:
            raise notion_failure(answer.status_code, _error_body(answer), action)
        try:
            return answer.json()
        except json.JSONDecodeError:
            raise ConnectorError(f"Notion answered {action.to_do} with something that is not JSON") from None

    def _finished(self, answer: httpx2.Response, action: _Action) -> dict[str, JsonValue]:
        body = self._succeeded(answer, action)
        if answer.status_code != HTTPStatus.ACCEPTED:
            return _validated(dict[str, JsonValue], body, action)
        task: PendingTask | SucceededTask | FailedTask = _validated(PendingTask, body, action)
        waited = 0.0
        while isinstance(task, PendingTask):
            pause = max(float(task.poll_after_seconds), SHORTEST_POLL_SECONDS)
            if waited + pause > LONGEST_TASK_WAIT_SECONDS:
                raise ConnectorError(
                    f"Notion had not finished {action.doing} after {waited:g} seconds (task {task.id}); the "
                    "change may still land, so read the page before publishing again"
                )
            self._sleep(pause)
            waited += pause
            task = self._followed(task.id, action)
        if isinstance(task, FailedTask):
            raise notion_failure(task.error.status or HTTPStatus.BAD_REQUEST, task.error, action)
        return task.result

    def _followed(self, task_id: str, action: _Action) -> PendingTask | SucceededTask | FailedTask:
        progress = _Action(f"read the progress of task {task_id}", "reading", writes=False)
        try:
            polled = self._succeeded(
                self._send("GET", f"/v1/async_tasks/{task_id}", None, progress), progress
            )
            return _validated(_ASYNC_TASK, polled, progress)
        except (ConnectorError, AuthError) as exc:
            raise ConnectorError(
                f"Notion accepted the request to {action.to_do} as task {task_id} but skaldr could not "
                f"follow it: {exc}; the change may still land, so read the page before publishing again"
            ) from exc

    def _send(self, method: str, path: str, body: JsonFields | None, action: _Action) -> httpx2.Response:
        answer = self._with_retries(method, path, body, action)
        if answer.status_code != HTTPStatus.UNAUTHORIZED:
            return answer
        self._tokens.renew()
        answer = self._with_retries(method, path, body, action)
        if answer.status_code == HTTPStatus.UNAUTHORIZED:
            raise AuthError(f"Notion refused the renewed sign-in{SIGN_IN_AGAIN}")
        return answer

    def _with_retries(
        self, method: str, path: str, body: JsonFields | None, action: _Action
    ) -> httpx2.Response:
        retrying = Retrying(
            stop=stop_after_attempt(RETRY_ATTEMPTS),
            wait=_wait_before_retrying,
            retry=retry_if_result(_deserves_a_retry(method))
            | retry_if_exception(_unreachable_on_a_read(method)),
            sleep=self._sleep,
            retry_error_callback=_last_answer,
        )
        answer: httpx2.Response = retrying(self._request, method, path, body, action)
        return answer

    def _request(self, method: str, path: str, body: JsonFields | None, action: _Action) -> httpx2.Response:
        headers = {"Authorization": f"Bearer {self._tokens.access_token}", "Notion-Version": NOTION_VERSION}
        try:
            return self._client.request(method, path, json=body, headers=headers)
        except httpx2.TransportError as exc:
            if method != "GET" and not isinstance(exc, NOT_SENT):
                raise ConnectorError(
                    f"Notion could not {action.to_do}: no answer arrived ({exc}); the change may have "
                    "landed, so read the page before publishing again"
                ) from None
            raise _UnreachableError(
                f"Notion could not {action.to_do}: could not reach Notion ({exc})"
            ) from None
