import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from enum import Enum
from http import HTTPStatus
from types import TracebackType
from typing import Final, TypeVar
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
from typing_extensions import Self

from skaldr.auth import HTTP_TIMEOUT_SECONDS
from skaldr.auth.store import JiraCredentials
from skaldr.errors import ConnectorError, ItemNotFoundError, WriteRejectedError
from skaldr.publish.jira.api import (
    Changelog,
    Comment,
    CreatedIssue,
    EntityProperty,
    Entry,
    Issue,
    JiraUser,
    Page,
    RemoteLink,
    RemoteLinks,
    Transition,
    Transitions,
)

API = "/rest/api/3"
MAX_ATTEMPTS = 4
FIRST_BACKOFF_SECONDS = 2
MAX_RETRY_AFTER_SECONDS = 60
PAGE_SIZE = 100
READ_METHODS = frozenset({"GET"})
JSON_CONTENT_TYPE = {"Content-Type": "application/json"}

Answer = TypeVar("Answer", bound=BaseModel)
_BACKOFF = wait_exponential(multiplier=FIRST_BACKOFF_SECONDS)


class _NoBody(Enum):
    NO_BODY = "no body"


NO_BODY: Final = _NoBody.NO_BODY


def _json_bytes(body: JsonValue) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _properties_body(properties: Sequence[EntityProperty]) -> list[JsonValue]:
    return [prop.model_dump() for prop in properties]


def _refusal_class(method: str) -> type[ConnectorError]:
    return ConnectorError if method in READ_METHODS else WriteRejectedError


class _ErrorBody(BaseModel):
    error_messages: list[str] = Field(default_factory=list[str], alias="errorMessages")
    errors: dict[str, str] = Field(default_factory=dict[str, str])


def issue_path(key: str, *rest: str) -> str:
    return "/".join([f"{API}/issue/{quote(key, safe='')}", *(quote(part, safe="") for part in rest)])


def _retry_after(response: httpx2.Response) -> int | None:
    text = response.headers.get("Retry-After", "").strip()
    return int(text) if text.isascii() and text.isdecimal() else None


def _wait(state: RetryCallState) -> float:
    outcome = state.outcome
    if outcome is not None and not outcome.failed:
        retry_after = _retry_after(outcome.result())
        if retry_after is not None:
            return retry_after
    return _BACKOFF(state)


def _worth_retrying(method: str) -> Callable[[httpx2.Response], bool]:
    def worth(response: httpx2.Response) -> bool:
        retry_after = _retry_after(response)
        if retry_after is not None and retry_after > MAX_RETRY_AFTER_SECONDS:
            return False
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            return True
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


def _when_to_try_again(response: httpx2.Response) -> str:
    seconds = _retry_after(response)
    if seconds is None:
        return "wait a minute and publish again"
    unit = "second" if seconds == 1 else "seconds"
    return f"Jira asked to wait {seconds} {unit}, so publish again after that"


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

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def myself(self) -> JiraUser:
        path = f"{API}/myself"
        return self._parsed(JiraUser, self._send("GET", path), path, "the signed-in account")

    def create_issue(
        self, fields: Mapping[str, JsonValue], properties: Sequence[EntityProperty]
    ) -> CreatedIssue:
        path = f"{API}/issue"
        body: dict[str, JsonValue] = {"fields": dict(fields), "properties": _properties_body(properties)}
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
            body["properties"] = _properties_body(properties)
        self._send("PUT", issue_path(key), key=key, body=body)

    def changelog(self, key: str) -> list[Changelog]:
        return self._every_entry(key, "changelog", Page[Changelog], "history")

    def comments(self, key: str) -> list[Comment]:
        return self._every_entry(key, "comment", Page[Comment], "list of comments")

    def _every_entry(self, key: str, listing: str, page_type: type[Page[Entry]], whole: str) -> list[Entry]:
        path = issue_path(key, listing)
        entries: list[Entry] = []
        while True:
            start = len(entries)
            params = {"startAt": start, "maxResults": PAGE_SIZE}
            response = self._send("GET", path, key=key, params=params)
            page = self._parsed(page_type, response, path, f"a page of the issue's {whole}")
            if page.start_at != start:
                raise ConnectorError(
                    f"Jira answered GET {path} with a page starting at entry {page.start_at} when skaldr "
                    f"asked for entry {start}, so skaldr cannot read the issue's whole {whole}"
                )
            entries += page.entries
            ended = page.is_last or (page.total is not None and len(entries) >= page.total)
            if ended or not page.entries:
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

    def remote_links(self, key: str) -> list[RemoteLink]:
        path = issue_path(key, "remotelink")
        response = self._send("GET", path, key=key)
        return list(self._parsed(RemoteLinks, response, path, "the issue's remote links").root)

    def put_remote_link(self, key: str, global_id: str, url: str, title: str) -> None:
        body: dict[str, JsonValue] = {"globalId": global_id, "object": {"url": url, "title": title}}
        self._send("POST", issue_path(key, "remotelink"), key=key, body=body)

    def delete_remote_link(self, key: str, global_id: str) -> None:
        self._send(
            "DELETE",
            issue_path(key, "remotelink"),
            key=key,
            params={"globalId": global_id},
            missing_is_an_answer=True,
        )

    def _send(
        self,
        method: str,
        path: str,
        *,
        key: str | None = None,
        params: Mapping[str, str | int] | None = None,
        body: JsonValue | _NoBody = NO_BODY,
        missing_is_an_answer: bool = False,
    ) -> httpx2.Response:
        def attempt() -> httpx2.Response:
            if isinstance(body, _NoBody):
                headers = None if method in READ_METHODS else JSON_CONTENT_TYPE
                return self._http.request(method, path, params=params, headers=headers)
            return self._http.request(
                method, path, params=params, content=_json_bytes(body), headers=JSON_CONTENT_TYPE
            )

        retrying = Retrying(
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=_wait,
            retry=retry_if_result(_worth_retrying(method)) | retry_if_exception(_dropped_read(method)),
            sleep=self._sleep,
            retry_error_callback=_last_attempt,
        )
        try:
            response: httpx2.Response = retrying(attempt)
        except httpx2.TransportError as exc:
            raise ConnectorError(f"could not reach Jira at {self.site} for {method} {path}: {exc}") from exc
        except httpx2.RequestError as exc:
            raise ConnectorError(f"the request {method} {path} to Jira at {self.site} failed: {exc}") from exc
        if missing_is_an_answer and response.status_code == HTTPStatus.NOT_FOUND:
            return response
        attempts: int = retrying.statistics["attempt_number"]
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
        refused = _refusal_class(method)
        if status == HTTPStatus.UNAUTHORIZED:
            raise refused(
                f"Jira at {self.site} rejected the sign-in (HTTP 401); the API token may have expired or "
                "been revoked, so run `skaldr auth jira`"
            )
        if status == HTTPStatus.NOT_FOUND and key is not None:
            raise ItemNotFoundError(
                f"Jira has no issue {key} that this account can see (HTTP 404 to {where})"
            )
        if status == HTTPStatus.TOO_MANY_REQUESTS:
            raise refused(
                f"Jira kept refusing {where} as too many requests (HTTP 429) after {_attempts(attempts)}; "
                f"{_when_to_try_again(response)}"
            )
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise ConnectorError(f"Jira answered HTTP {status} to {where}{explained}")
        raise refused(f"Jira refused {where} (HTTP {status}){explained}")

    def _parsed(self, model: type[Answer], response: httpx2.Response, path: str, what: str) -> Answer:
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            raise ConnectorError(f"Jira's answer to {response.request.method} {path} is not {what}") from exc
