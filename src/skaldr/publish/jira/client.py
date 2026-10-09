import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from http import HTTPStatus
from typing import TypeVar
from urllib.parse import quote

import httpx2
from pydantic import BaseModel, Field, JsonValue, ValidationError
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from skaldr.auth import HTTP_TIMEOUT_SECONDS
from skaldr.auth.store import JiraCredentials
from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.jira.api import (
    Changelog,
    ChangelogPage,
    CreatedIssue,
    EntityProperty,
    Issue,
    JiraUser,
    Transition,
    Transitions,
)

API = "/rest/api/3"
ATTEMPTS = 4
FIRST_BACKOFF_SECONDS = 2
LONGEST_RETRY_AFTER_SECONDS = 60
CHANGELOG_PAGE_SIZE = 100
READ_METHODS = frozenset({"GET"})

Answer = TypeVar("Answer", bound=BaseModel)
_BACKOFF = wait_exponential(multiplier=FIRST_BACKOFF_SECONDS)


class _ErrorBody(BaseModel):
    error_messages: list[str] = Field(default_factory=list[str], alias="errorMessages")
    errors: dict[str, str] = Field(default_factory=dict[str, str])


def issue_path(key: str, *rest: str) -> str:
    return "/".join([f"{API}/issue/{quote(key, safe='')}", *(quote(part, safe="") for part in rest)])


def _retry_after(response: httpx2.Response) -> float | None:
    text = response.headers.get("Retry-After", "").strip()
    return float(text) if text.isdigit() else None


def _wait(state: RetryCallState) -> float:
    outcome = state.outcome
    if outcome is not None and not outcome.failed:
        retry_after = _retry_after(outcome.result())
        if retry_after is not None:
            return retry_after
    return _BACKOFF(state)


def _worth_retrying(method: str) -> Callable[[httpx2.Response], bool]:
    def worth(response: httpx2.Response) -> bool:
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            retry_after = _retry_after(response)
            return retry_after is None or retry_after <= LONGEST_RETRY_AFTER_SECONDS
        return method in READ_METHODS and response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR

    return worth


def _dropped_read(method: str) -> Callable[[BaseException], bool]:
    return lambda error: method in READ_METHODS and isinstance(error, httpx2.TransportError)


def _last_attempt(state: RetryCallState) -> httpx2.Response:
    if state.outcome is None:
        raise AssertionError("tenacity stopped before any attempt")
    answer: httpx2.Response = state.outcome.result()
    return answer


def _detail(response: httpx2.Response) -> str:
    try:
        body = _ErrorBody.model_validate_json(response.content)
    except ValidationError:
        return ""
    return "; ".join([*body.error_messages, *(f"{name}: {message}" for name, message in body.errors.items())])


def _attempts(count: int) -> str:
    return "1 attempt" if count == 1 else f"{count} attempts"


class JiraClient:
    def __init__(
        self,
        credentials: JiraCredentials,
        *,
        transport: httpx2.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.site = credentials.site
        self._sleep = sleep
        self._http = httpx2.Client(
            base_url=credentials.site,
            auth=(credentials.email, credentials.api_token),
            headers={"Accept": "application/json"},
            timeout=HTTP_TIMEOUT_SECONDS,
            transport=transport,
        )

    def myself(self) -> JiraUser:
        path = f"{API}/myself"
        return self._parsed(JiraUser, self._send("GET", path), path, "the signed-in account")

    def create_issue(
        self, fields: Mapping[str, JsonValue], properties: Sequence[EntityProperty]
    ) -> CreatedIssue:
        path = f"{API}/issue"
        body: dict[str, JsonValue] = {
            "fields": dict(fields),
            "properties": [prop.model_dump() for prop in properties],
        }
        return self._parsed(CreatedIssue, self._send("POST", path, body=body), path, "the created issue")

    def get_issue(self, key: str, field_names: Iterable[str]) -> Issue:
        path = issue_path(key)
        response = self._send("GET", path, key=key, params={"fields": ",".join(field_names)})
        return self._parsed(Issue, response, path, "the issue skaldr asked for")

    def edit_issue(
        self, key: str, fields: Mapping[str, JsonValue], properties: Sequence[EntityProperty] = ()
    ) -> None:
        body: dict[str, JsonValue] = {"fields": dict(fields)}
        if properties:
            body["properties"] = [prop.model_dump() for prop in properties]
        self._send("PUT", issue_path(key), key=key, body=body)

    def changelog(self, key: str) -> list[Changelog]:
        path = issue_path(key, "changelog")
        entries: list[Changelog] = []
        while True:
            params = {"startAt": len(entries), "maxResults": CHANGELOG_PAGE_SIZE}
            response = self._send("GET", path, key=key, params=params)
            page = self._parsed(ChangelogPage, response, path, "a page of the issue's changelog")
            entries += page.values
            ended = page.is_last or (page.total is not None and len(entries) >= page.total)
            if ended or not page.values:
                return entries

    def get_property(self, key: str, name: str) -> EntityProperty | None:
        path = issue_path(key, "properties", name)
        response = self._send("GET", path, key=key, missing_is_an_answer=True)
        if response.status_code == HTTPStatus.NOT_FOUND:
            return None
        return self._parsed(EntityProperty, response, path, "an issue property")

    def put_property(self, key: str, name: str, value: JsonValue) -> None:
        self._send("PUT", issue_path(key, "properties", name), key=key, body=value)

    def transitions(self, key: str) -> list[Transition]:
        path = issue_path(key, "transitions")
        response = self._send("GET", path, key=key)
        return self._parsed(Transitions, response, path, "the issue's transitions").transitions

    def transition(self, key: str, transition_id: str) -> None:
        body: dict[str, JsonValue] = {"transition": {"id": transition_id}}
        self._send("POST", issue_path(key, "transitions"), key=key, body=body)

    def add_comment(self, key: str, body: JsonValue) -> None:
        self._send("POST", issue_path(key, "comment"), key=key, body={"body": body})

    def _send(
        self,
        method: str,
        path: str,
        *,
        key: str | None = None,
        params: Mapping[str, str | int] | None = None,
        body: JsonValue = None,
        missing_is_an_answer: bool = False,
    ) -> httpx2.Response:
        attempts = 0

        def attempt() -> httpx2.Response:
            nonlocal attempts
            attempts += 1
            if body is None:
                return self._http.request(method, path, params=params)
            return self._http.request(method, path, params=params, json=body)

        retrying = Retrying(
            stop=stop_after_attempt(ATTEMPTS),
            wait=_wait,
            retry=retry_if_result(_worth_retrying(method)) | retry_if_exception(_dropped_read(method)),
            sleep=self._sleep,
            retry_error_callback=_last_attempt,
        )
        try:
            response: httpx2.Response = retrying(attempt)
        except httpx2.TransportError as exc:
            raise ConnectorError(f"could not reach Jira at {self.site} for {method} {path}: {exc}") from exc
        if missing_is_an_answer and response.status_code == HTTPStatus.NOT_FOUND:
            return response
        self._refuse_a_failure(method, path, key, response, attempts)
        return response

    def _refuse_a_failure(
        self, method: str, path: str, key: str | None, response: httpx2.Response, attempts: int
    ) -> None:
        status = response.status_code
        if HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
            return
        where = f"{method} {path}"
        detail = _detail(response)
        explained = f": {detail}" if detail else ""
        if status == HTTPStatus.UNAUTHORIZED:
            raise ConnectorError(
                f"Jira at {self.site} rejected the sign-in (HTTP 401); the API token may have expired or "
                "been revoked, so run `skaldr auth jira`"
            )
        if status == HTTPStatus.NOT_FOUND and key is not None:
            raise ItemNotFoundError(
                f"Jira has no issue {key} that this account can see (HTTP 404 to {where})"
            )
        if status == HTTPStatus.TOO_MANY_REQUESTS:
            raise ConnectorError(
                f"Jira kept refusing {where} as too many requests (HTTP 429) after {_attempts(attempts)}; "
                "wait a minute and publish again"
            )
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise ConnectorError(f"Jira answered HTTP {status} to {where}{explained}")
        refusal = f"Jira refused {where} (HTTP {status}){explained}"
        if method in READ_METHODS:
            raise ConnectorError(refusal)
        raise WriteRejectedError(refusal)

    def _parsed(self, model: type[Answer], response: httpx2.Response, path: str, what: str) -> Answer:
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            raise ConnectorError(f"Jira's answer to {response.request.method} {path} is not {what}") from exc
