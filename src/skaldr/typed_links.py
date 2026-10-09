import re
from dataclasses import dataclass
from datetime import date
from typing import Final

from skaldr.errors import ReportError
from skaldr.models import PERSON_KEY_PATTERN
from skaldr.patterns import SLUG_PATTERN

DATE_SCHEME: Final = "date:"
USER_SCHEME: Final = "user:"
JIRA_SCHEME: Final = "jira:"
DOC_SCHEME: Final = "doc:"
TYPED_LINK_SCHEMES: Final = (DATE_SCHEME, USER_SCHEME, JIRA_SCHEME, DOC_SCHEME)

_ISO_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_RANGE_SEPARATOR: Final = "/"
_ISSUE_KEY: Final = re.compile(r"[A-Z][A-Z0-9_]*-[0-9]+")
_PERSON_KEY: Final = re.compile(PERSON_KEY_PATTERN)
_DOCUMENT_ID: Final = re.compile(SLUG_PATTERN)
_SECTION_SEPARATOR: Final = "#"


@dataclass(frozen=True)
class DateTarget:
    start: date
    end: date | None


@dataclass(frozen=True)
class DocumentTarget:
    doc_id: str
    section: str | None


def _bad_date(value: str, target: str) -> ReportError:
    return ReportError(f"invalid date '{value}' in link target {target}: write a date as YYYY-MM-DD")


def _day(value: str, target: str) -> date:
    if not _ISO_DATE.fullmatch(value):
        raise _bad_date(value, target)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise _bad_date(value, target) from error


def date_target(target: str) -> DateTarget:
    start_text, separator, end_text = target.removeprefix(DATE_SCHEME).partition(_RANGE_SEPARATOR)
    start = _day(start_text, target)
    if not separator:
        return DateTarget(start, None)
    end = _day(end_text, target)
    if end < start:
        raise ReportError(f"date range {target} ends before it starts: write the earlier date first")
    return DateTarget(start, end)


def issue_key(target: str) -> str:
    key = target.removeprefix(JIRA_SCHEME)
    if not _ISSUE_KEY.fullmatch(key):
        raise ReportError(
            f"invalid Jira issue key '{key}' in link target {target}: write a project key in capitals, "
            "a hyphen and a number, as in jira:ABC-123"
        )
    return key


def person_key(target: str) -> str:
    key = target.removeprefix(USER_SCHEME)
    if not _PERSON_KEY.fullmatch(key):
        raise ReportError(
            f"invalid person key '{key}' in link target {target}: a person key is letters, digits, '_' or "
            "'-' only"
        )
    return key


def document_target(target: str) -> DocumentTarget:
    doc_id, separator, section = target.removeprefix(DOC_SCHEME).partition(_SECTION_SEPARATOR)
    if not _DOCUMENT_ID.fullmatch(doc_id):
        raise ReportError(
            f"invalid document id '{doc_id}' in link target {target}: a document id is lowercase letters "
            "and digits joined by single hyphens"
        )
    if separator and not _DOCUMENT_ID.fullmatch(section):
        raise ReportError(
            f"invalid section id '{section}' in link target {target}: a section id is lowercase letters "
            "and digits joined by single hyphens"
        )
    return DocumentTarget(doc_id, section if separator else None)
