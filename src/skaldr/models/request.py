import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, NamedTuple

from pydantic import AfterValidator, Field, model_validator

from skaldr.errors import ReportError
from skaldr.frozen_model import FrozenModel
from skaldr.lexers import find_lexer
from skaldr.models.base import BlockBase
from skaldr.models.primitives import (
    ANCHOR_ID_PATTERN,
    MAX_STRIP_LABELS,
    NUMBER_GUARD,
    REFERENCE_KEY_PATTERN,
    NonBlank,
    NonBlankRichText,
    check_distinct_strip_labels,
)

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
VARIABLE_TOKEN = re.compile(rf"\{{\{{\s*({REFERENCE_KEY_PATTERN})\s*\}}\}}")
CaseTone = Literal["neutral", "info", "success", "warning", "danger"]


def _command_without_block_scalar_trailing_newline(text: str) -> str:
    trimmed = text.rstrip("\n")
    if not trimmed.strip():
        raise ValueError("command must not be blank (omit it instead)")
    return trimmed


CommandText = Annotated[str, AfterValidator(_command_without_block_scalar_trailing_newline)]


def _non_blank_query_without_block_scalar_trailing_newline(text: str) -> str:
    trimmed = text.rstrip("\n")
    if not trimmed.strip():
        raise ValueError("query must not be blank (omit it instead)")
    return trimmed


def _pygments_lexer_name(language: str) -> str:
    if find_lexer(language) is None:
        raise ValueError(f"`{language}` is not a Pygments lexer name")
    return language


class RequestQuery(FrozenModel):
    runner: NonBlank = Field(
        description="Free-text label for the tool the query runs in, shown with it, such as "
        "`mongosh, orders database` or `psql, reporting replica`."
    )
    lang: Annotated[str, AfterValidator(_pygments_lexer_name)] = Field(
        description="The query's language as a Pygments lexer name, such as `json`, `sql` or `js`. It "
        "highlights the query on the page and labels the fence in the Markdown exports."
    )
    content: Annotated[str, AfterValidator(_non_blank_query_without_block_scalar_trailing_newline)] = Field(
        description="The query text the reader copies and runs in the named tool. May carry "
        "`{{variable}}` tokens, written in as the reader types them."
    )


class ComposedCall(NamedTuple):
    method: HttpMethod
    url: str


class RequestVariable(FrozenModel):
    name: str = Field(
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="The token a reader fills, written `{{name}}` in the url, a header value or the "
        "body. ASCII letters, digits, _ and -.",
    )
    label: NonBlank | None = Field(
        default=None, description="Field label above the input. Defaults to `name`."
    )
    example: NonBlank | None = Field(
        default=None,
        description="A sample value, prefilled into the input so the request can be run as it stands. "
        "On a `secret` it is placeholder text only and is never prefilled, since a prefilled secret "
        "would be a secret stored in the YAML.",
    )
    secret: bool = Field(
        default=False,
        description="Never prefill this field from `example`, and mark it in the form as a value that "
        "is not saved. What the reader types stays in their browser tab: it reaches neither the page's "
        "embedded source nor a `--pdf` render, which loads the file fresh with the form empty. Printing "
        "from a tab they have filled in does capture it, in the form and in the command. The input is "
        "not masked, because the same value is shown in full in the command right below it.",
    )


class RequestResponse(FrozenModel):
    status: Annotated[int, Field(ge=100, le=599), NUMBER_GUARD] | None = Field(
        default=None,
        description="The status you recorded. Omit for a response with no status line, such as a bare "
        "token from `curl -s`. The case's tone follows this number, so you never pick one.",
    )
    reason: str | None = Field(
        default=None,
        description="The reason phrase. Omit and skaldr supplies the standard text for the status, "
        "which is what an HTTP/2 response needs since it carries no reason phrase.",
    )
    headers: dict[str, str | list[str]] = Field(
        default_factory=dict,
        description="Response headers worth keeping, in the order you want them read. Give a list for "
        "a header that legitimately repeats, such as `Set-Cookie`.",
    )
    body: str = Field(
        description="The body, verbatim. A one-line JSON object or array, as `curl -s` or `jq -c` "
        "prints it, is pretty-printed for display; a body you laid out across lines is shown as written."
    )

    @model_validator(mode="after")
    def _shape(self) -> "RequestResponse":
        for name in self.headers:
            if not name.strip():
                raise ValueError("response header name must not be blank")
        return self


def check_header_map(
    headers: Mapping[str, str] | None, what: Literal["request header", "request case header"]
) -> None:
    """Every rule a set of headers on one call obeys, wherever it is written.

    A name is case-insensitive on the wire, so two spellings of one name are that header written
    twice: the command a reader pastes would carry both, and which one the server honours is not
    ours to decide."""
    spellings: dict[str, str] = {}
    for name, value in (headers or {}).items():
        if not name.strip():
            raise ValueError(f"{what} name must not be blank")
        if not value.strip():
            raise ValueError(f"{what} `{name}` must not have a blank value")
        seen = spellings.get(name.lower())
        if seen is not None:
            raise ValueError(f"{what}s `{seen}` and `{name}` differ only in case, so they name one header")
        spellings[name.lower()] = name


class RequestCase(FrozenModel):
    label: NonBlank = Field(description="Tab label, and the case's heading when printed.")
    value: NonBlank | None = Field(
        default=None,
        description="What this case supplies for the block's `case_variable`. Defaults to `label`, "
        "which is what you want when the cases are resource names.",
    )
    values: Annotated[dict[str, NonBlank], Field(min_length=1)] | None = Field(
        default=None,
        description="What this case supplies for several of the block's declared `variables` at once, "
        "as a map of variable name to value. Each name must be a declared variable. Use it when cases "
        "differ by more than one value, so a shared `command` or built call is written once. A declared "
        "variable the case leaves out stays a field the reader fills on this case's tab. Cannot be "
        "combined with `value`, or on a request that declares a `case_variable`.",
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description="Replace the request's headers for this case alone. Omit to inherit them; give an "
        "empty map to send none, which is how you record what happens with the auth header removed.",
    )
    headers_add: dict[str, str] | None = Field(
        default=None,
        description="Add to the request's headers for this case, replacing a name it already sets and "
        "leaving the rest. Use it when cases share a credential and differ in one header, so the shared "
        "one is written once. Cannot be combined with `headers`, which replaces them outright.",
    )
    command: CommandText | None = Field(
        default=None,
        description="Replace the request's `command` for this case alone, for a control that differs "
        "from the finding by more than one value. Only on a request that runs a `command`.",
    )
    tone: CaseTone | None = Field(
        default=None,
        description="Colour this case's tab and verdict when its response carries no `status`, such as "
        "the output of a `curl -s | jq` command: `warning` for a finding, `success` for a control that "
        "passes. A recorded status decides the tone by itself, so the two are never set together.",
    )
    response: RequestResponse = Field(description="What came back when you ran it.")
    verdict: NonBlankRichText | None = Field(
        default=None,
        description="Rich-text reading of this response: what you expected, what you got, what it "
        "means. The one part of the block a reader cannot work out for themselves.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "RequestCase":
        if self.headers is not None and self.headers_add is not None:
            raise ValueError(
                "a request case sets headers and headers_add together: headers replaces and "
                "headers_add layers, so state the headers you want once, under headers"
            )
        for source in (self.headers, self.headers_add):
            check_header_map(source, "request case header")
        if self.tone is not None and self.response.status is not None:
            raise ValueError(
                f"case '{self.label}' sets a tone and records status {self.response.status}: the status "
                "already decides the tone, so drop `tone`"
            )
        return self


class _RequestCore(FrozenModel):
    """One recorded call, composed from its HTTP fields or given as an exact command, and the outcomes
    it produced. Shared by a standalone `request` and by a step of a `request_flow`, which differ only
    in where their variables come from."""

    label: NonBlank = Field(description="What the call is for, shown in the header.")
    method: HttpMethod | None = Field(
        default=None,
        description="The HTTP method. Required unless the call runs a `command` or records a `query`.",
    )
    url: str | None = Field(
        default=None,
        min_length=1,
        description="The full URL. May carry `{{variable}}` tokens. Required unless the call runs a "
        "`command` or records a `query`.",
    )
    command: CommandText | None = Field(
        default=None,
        description="A shell command the reader copies and runs exactly as written, in place of the "
        "curl skaldr would build from `method`, `url`, `headers` and `body`. Use it when the call needs "
        "what those fields cannot say: a secret manager supplying the credential, a proxy, a `| jq` "
        "that shapes the output. May carry `{{variable}}` tokens, written in as the reader types them "
        "with no shell quoting added. Cannot be combined with `method`, `url`, `headers` or `body`.",
    )
    command_note: NonBlankRichText | None = Field(
        default=None,
        description="Rich-text line under the command explaining why it is shaped the way it is, such "
        "as what a `jq` filter makes visible. The verdict stays about what came back.",
    )
    query: RequestQuery | None = Field(
        default=None,
        description="Evidence that is not a shell command: a database aggregation, a SQL query or an MCP "
        "call, run in the tool named by its `runner`. It is shown highlighted with a Copy button, and "
        "the cases record what came back. Cannot be combined with `method`, `url`, `headers`, `body` "
        "or `command`.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Request headers as a map, in the order they should read. A value may carry "
        "`{{variable}}` tokens.",
    )
    body: NonBlank | None = Field(
        default=None,
        description="Request body, sent as `--data`. May carry `{{variable}}` tokens, so a credential "
        "can sit inside a JSON login payload without ever being written here.",
    )
    case_variable: str | None = Field(
        default=None,
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="The `{{name}}` each case supplies, for cases that differ by one value such as a "
        "resource name. Omit when the cases differ by headers instead, or when there is only one.",
    )
    cases: list[RequestCase] = Field(
        min_length=1,
        description="One entry per recorded outcome. Tabs on screen, stacked under their own headings "
        "when printed, because a tab must never hide evidence on paper.",
    )

    def referenced_variables(self) -> set[str]:
        """Every `{{name}}` this call interpolates, across the url, the command, the header values, the
        body and each case's own command.

        A case's headers count whichever way it sets them: `headers` replaces the request's and
        `headers_add` layers over them, and both are interpolated the same way at render time."""
        case_headers = (
            value
            for case in self.cases
            for source in (case.headers, case.headers_add)
            for value in (source or {}).values()
        )
        case_commands = (case.command or "" for case in self.cases)
        scan = " ".join(
            (
                self.url or "",
                self.command or "",
                self.query.content if self.query else "",
                *self.headers.values(),
                self.body or "",
                *case_headers,
                *case_commands,
            )
        )
        return {match.group(1) for match in VARIABLE_TOKEN.finditer(scan)}

    def composed_call(self) -> ComposedCall:
        if self.method is None or self.url is None:
            raise ReportError(f"request '{self.label}' runs a command, so skaldr composes no call for it")
        return ComposedCall(self.method, self.url)

    def case_axis(self) -> set[str]:
        """The case variable as a set, empty when the call declares none."""
        return {self.case_variable} if self.case_variable else set()

    @model_validator(mode="after")
    def _core_shape(self) -> "_RequestCore":
        check_distinct_strip_labels((case.label for case in self.cases), "request repeats a case label")
        if len(self.cases) > MAX_STRIP_LABELS:
            raise ValueError(
                f"a request records at most {MAX_STRIP_LABELS} cases, and this one has "
                f"{len(self.cases)}; split it into blocks a reader can take in"
            )
        for case in self.cases:
            self._check_how_the_case_fills_its_values(case)
        check_header_map(self.headers, "request header")
        if self.query is not None:
            self._check_query_call()
        elif self.command is None:
            self._check_composed_call()
        else:
            self._check_command_call()
        return self

    def _check_query_call(self) -> None:
        composed_fields = {
            "method": self.method,
            "url": self.url,
            "headers": self.headers or None,
            "body": self.body,
            "command": self.command,
        }
        for name, value in composed_fields.items():
            if value is not None:
                raise ValueError(
                    f"request '{self.label}' sets `query` and `{name}`: a query is recorded as written, "
                    f"so skaldr builds no curl and `{name}` would never reach it"
                )
        if self.command_note is not None:
            raise ValueError(
                f"request '{self.label}' sets a command_note on a query: put the note in a verdict"
            )
        for case in self.cases:
            for name, value in (
                ("command", case.command),
                ("headers", case.headers),
                ("headers_add", case.headers_add),
            ):
                if value is not None:
                    raise ValueError(
                        f"case '{case.label}' sets `{name}` on a request that records a query, which has "
                        "no command or headers of its own: write the change into the query"
                    )

    def _check_how_the_case_fills_its_values(self, case: RequestCase) -> None:
        if case.value is not None and case.values is not None:
            raise ValueError(
                f"case '{case.label}' sets value and values together: value fills the case_variable and "
                "values fills declared variables, so give the case one of them"
            )
        if case.values is not None and self.case_variable is not None:
            raise ValueError(
                f"case '{case.label}' sets values on a request that declares case_variable "
                f"`{self.case_variable}`: values and case_variable are two ways to fill a case, so use one"
            )
        if case.value is not None and self.case_variable is None:
            raise ValueError(
                f"case '{case.label}' sets a value but the request declares no case_variable, "
                "so there is nothing for it to fill"
            )

    def referenced_by_case(self, case: RequestCase) -> set[str]:
        headers = case.headers if case.headers is not None else self.headers
        scan = " ".join(
            (
                self.url or "",
                case.command or self.command or "",
                self.query.content if self.query is not None else "",
                *headers.values(),
                *(case.headers_add or {}).values(),
                self.body or "",
            )
        )
        return {match.group(1) for match in VARIABLE_TOKEN.finditer(scan)}

    def check_values_keys(self, variables: Sequence[RequestVariable], owner: str) -> None:
        known = {variable.name: variable for variable in variables}
        for case in self.cases:
            used = self.referenced_by_case(case)
            for name in case.values or {}:
                if name not in known:
                    raise ValueError(
                        f"case '{case.label}' sets `{name}` under values, but the {owner} declares no "
                        f"variable named `{name}`"
                    )
                if known[name].secret:
                    raise ValueError(
                        f"case '{case.label}' sets `{name}` under values, but `{name}` is a secret "
                        "variable the reader supplies"
                    )
                if name not in used:
                    raise ValueError(
                        f"case '{case.label}' sets `{name}` under values, but nothing it sends uses "
                        f"`{{{{{name}}}}}`"
                    )

    def case_bindings(self, case: RequestCase) -> dict[str, str]:
        if self.case_variable is not None:
            return {self.case_variable: case.value or case.label}
        return dict(case.values or {})

    def _check_composed_call(self) -> None:
        if self.method is None or self.url is None:
            raise ValueError(
                f"request '{self.label}' needs `method` and `url` to build a curl, or a `command` to run "
                "as written, or a `query` to record as written"
            )
        for case in self.cases:
            if case.command is not None:
                raise ValueError(
                    f"case '{case.label}' sets a command but the request builds a curl from `method` and "
                    "`url`: set `command` on the request to run its cases as written"
                )
        if self.command_note is not None:
            raise ValueError(
                f"request '{self.label}' sets a command_note but runs no command: put the note in a verdict"
            )

    def _check_command_call(self) -> None:
        composed_fields = {
            "method": self.method,
            "url": self.url,
            "headers": self.headers or None,
            "body": self.body,
        }
        for name, value in composed_fields.items():
            if value is not None:
                raise ValueError(
                    f"request '{self.label}' sets `command` and `{name}`: a command runs exactly as "
                    f"written, so skaldr builds no curl and `{name}` would never reach it"
                )
        for case in self.cases:
            for name, value in (("headers", case.headers), ("headers_add", case.headers_add)):
                if value is not None:
                    raise ValueError(
                        f"case '{case.label}' sets `{name}` on a request that runs a command, which sends "
                        "no headers of its own: write them into the command"
                    )


class _VariableOwner(FrozenModel):
    """The block a reader's fields belong to."""

    variables: list[RequestVariable] = Field(
        default_factory=list[RequestVariable],
        description="The values a reader supplies. A `{{name}}` declared here is a runtime blank the "
        "reader fills, so `--check --strict` leaves it alone; an undeclared one is still an unfilled "
        "placeholder and still fails strict, which is what catches a mistyped name.",
    )
    id: str | None = Field(
        default=None,
        pattern=rf"^{ANCHOR_ID_PATTERN}$",
        description="Optional stable id, unique across the page's request blocks. It keys what a "
        "reader's non-secret fields are remembered under while their tab is open, so set one when two "
        "blocks share a label, and keep it fixed if you want those values to survive a rename.",
    )


class Request(_RequestCore, _VariableOwner, BlockBase):
    type: Literal["request"]

    def resolvable_variables(self) -> set[str]:
        """Every name the block can fill by itself: the reader's fields plus the case axis."""
        return {variable.name for variable in self.variables} | self.case_axis()

    @model_validator(mode="after")
    def _shape(self) -> "Request":
        declared = [variable.name for variable in self.variables]
        repeated = {name for name in declared if declared.count(name) > 1}
        if repeated:
            raise ValueError(f"request declares a variable twice: {', '.join(sorted(repeated))}")
        if self.case_variable is not None and self.case_variable in declared:
            raise ValueError(
                f"`{self.case_variable}` is both the case_variable and a declared variable: each case "
                "supplies it, so it must not also be a field the reader fills"
            )
        self.check_values_keys(self.variables, "request")
        unused = self.resolvable_variables() - self.referenced_variables()
        if unused:
            raise ValueError(
                f"request declares {', '.join(sorted(unused))} but never uses "
                f"{'them' if len(unused) > 1 else 'it'}; every variable needs a `{{{{name}}}}` to fill"
            )
        return self


class RequestCapture(FrozenModel):
    name: str = Field(
        pattern=rf"^{REFERENCE_KEY_PATTERN}$",
        description="The name this step produces. A later step writes it as `{{name}}` and the reader "
        "never types it.",
    )
    source: Literal["body"] | None = Field(
        default=None,
        description="Take the whole response body, trimmed. For an endpoint that answers with a bare "
        "token and no JSON wrapper. Use this or `json_path`, not both.",
    )
    json_path: str | None = Field(
        default=None,
        pattern=r"^\$\.[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$",
        description="A dotted path into a JSON response body, written `$.access_token` or "
        "`$.data.token`. Object keys only, since that is what the page resolves; an array index is "
        "not part of the path language. Use this or `source`, not both.",
    )
    secret: bool = Field(
        default=False,
        description="Show the captured value as a count rather than in the field that reports it. The "
        "value still appears in the command of any step that interpolates it.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "RequestCapture":
        if (self.source is None) == (self.json_path is None):
            raise ValueError(
                f"capture `{self.name}` takes `source: body` or a `json_path`, exactly one of the two"
            )
        return self


class RequestStep(_RequestCore):
    captures: list[RequestCapture] = Field(
        default_factory=list[RequestCapture],
        description="Values this step's response produces for later steps to interpolate.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "RequestStep":
        names = [capture.name for capture in self.captures]
        repeated = {name for name in names if names.count(name) > 1}
        if repeated:
            raise ValueError(f"step captures the same name twice: {', '.join(sorted(repeated))}")
        if self.captures and len(self.cases) > 1:
            raise ValueError(
                f"step '{self.label}' captures a value and records {len(self.cases)} cases; a capture "
                "reads one definite response, so a step that produces a value keeps a single case"
            )
        if self.captures and self.query is not None:
            raise ValueError(
                f"step '{self.label}' captures a value but records a query: a capture reads a response "
                "the reader pastes, and a query has nowhere to paste one"
            )
        return self


class RequestFlow(_VariableOwner, BlockBase):
    type: Literal["request_flow"]
    label: NonBlank = Field(description="What the flow is for, shown in the block header.")
    steps: list[RequestStep] = Field(
        min_length=2,
        description="The calls in the order they run. A flow of one step is a `request`, so use that.",
    )

    def produced_by(self, index: int) -> set[str]:
        """Names captured by the steps before `index`, which is what that step may interpolate."""
        return {capture.name for step in self.steps[:index] for capture in step.captures}

    def resolvable_variables(self) -> set[str]:
        """Every name the block fills by itself: the reader's fields, each step's case axis, and every
        captured name."""
        names = {variable.name for variable in self.variables}
        for step in self.steps:
            names |= step.case_axis() | {capture.name for capture in step.captures}
        return names

    def unresolved_variables(self) -> set[str]:
        """Names a step interpolates that nothing can fill by the time that step runs. A capture from a
        later step does not count: the value does not exist yet when the reader reaches this one."""
        declared = {variable.name for variable in self.variables}
        missing: set[str] = set()
        for index, step in enumerate(self.steps):
            available = declared | step.case_axis() | self.produced_by(index)
            missing |= step.referenced_variables() - available
        return missing

    @model_validator(mode="after")
    def _shape(self) -> "RequestFlow":
        declared = [variable.name for variable in self.variables]
        repeated = {name for name in declared if declared.count(name) > 1}
        if repeated:
            raise ValueError(f"flow declares a variable twice: {', '.join(sorted(repeated))}")
        for step in self.steps:
            step.check_values_keys(self.variables, "flow")
        captured = [capture.name for step in self.steps for capture in step.captures]
        clashing = {name for name in captured if name in declared}
        if clashing:
            raise ValueError(
                f"{', '.join(sorted(clashing))} is both captured and declared: a step produces it, so "
                "it must not also be a field the reader fills"
            )
        duplicated = {name for name in captured if captured.count(name) > 1}
        if duplicated:
            raise ValueError(f"two steps capture the same name: {', '.join(sorted(duplicated))}")
        for index, step in enumerate(self.steps):
            late = step.referenced_variables() & (set(captured) - self.produced_by(index))
            if late:
                raise ValueError(
                    f"step {index + 1} uses {', '.join(sorted(late))} before the step that captures "
                    f"{'them' if len(late) > 1 else 'it'} has run"
                )
        unused = self.resolvable_variables() - {
            name for step in self.steps for name in step.referenced_variables()
        }
        if unused:
            raise ValueError(
                f"flow declares or captures {', '.join(sorted(unused))} but no step uses "
                f"{'them' if len(unused) > 1 else 'it'}"
            )
        return self
