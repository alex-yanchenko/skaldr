import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import Final, Literal, Protocol, cast, get_args

from pydantic import TypeAdapter, ValidationError
from typing_extensions import assert_never

from skaldr.errors import ReportError
from skaldr.mathml import refuse_invalid_math
from skaldr.models import (
    ALLOWED_URL_SCHEMES,
    REFERENCE_KEY_PATTERN,
    BadgeColorLiteral,
    Report,
    Tone,
    ToneLiteral,
)

MarkerStyle = Literal["bold", "italic", "strike"]
StyleName = Literal[MarkerStyle, "underline"]
ScriptPosition = Literal["subscript", "superscript"]
SCRIPT_HTML_TAG: Final[Mapping[ScriptPosition, str]] = {"subscript": "sub", "superscript": "sup"}


@dataclass(frozen=True)
class Plain:
    text: str


@dataclass(frozen=True)
class Code:
    text: str


@dataclass(frozen=True)
class Link:
    label: "Rich"
    url: str


@dataclass(frozen=True)
class AnchorLink:
    label: "Rich"
    anchor: str


@dataclass(frozen=True)
class Citation:
    key: str
    number: int
    url: str | None = None


@dataclass(frozen=True)
class Placeholder:
    name: str


@dataclass(frozen=True)
class Styled:
    style: StyleName
    runs: "Rich"


@dataclass(frozen=True)
class ScriptText:
    position: ScriptPosition
    text: str


@dataclass(frozen=True)
class Tinted:
    tone: ToneLiteral | None
    background: ToneLiteral | None
    runs: "Rich"


@dataclass(frozen=True)
class InlineMath:
    expression: str


Run = Plain | Code | Link | AnchorLink | Citation | Placeholder | Styled | ScriptText | Tinted | InlineMath
Rich = tuple[Run, ...]

_MATH_OR_CODE_SPAN = re.compile(r"\$`([^`]+)`\$|`([^`]+)`")
_FOOTNOTE = re.compile(rf"\[\^({REFERENCE_KEY_PATTERN})\]")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_PLACEHOLDER_NAME = re.compile(REFERENCE_KEY_PATTERN)
_SENTINEL = re.compile(r"\x00(\d+)\x00")
_LINK_TARGET = re.compile(r"(?<=\])\([^)\s]+\)")
_LINK_TARGET_MARK = re.compile(r"\x01(\d+)\x01")
_STASH_MARKER: Final = "\x00"
_LINK_TARGET_MARKER: Final = "\x01"
_SET_ASIDE_MARKERS: Final = (_STASH_MARKER, _LINK_TARGET_MARKER)


def _attribute_list(excluded: str) -> str:
    return rf"\{{(?=[^{{}}{excluded}]*?(?<![^\s{{])(?:tone|bg)\s*=)([^{{}}{excluded}]*)\}}"


_ATTRIBUTE_SPAN = re.compile(r"\[([^\[\]]+)\]" + _attribute_list("".join(_SET_ASIDE_MARKERS)))
_STRAY_ATTRIBUTE_LIST = re.compile(r"\]" + _attribute_list(""))
_SPAN_ATTRIBUTES: Final = frozenset({"tone", "bg"})
_TONE: Final = TypeAdapter[ToneLiteral](Tone)
_PALETTE_ONLY_NAMES: Final = tuple(
    name for name in get_args(BadgeColorLiteral) if name not in get_args(ToneLiteral)
)
_SCRIPT_TEXT: Final = r"((?:[^\W_]|[-+=().,'*" + "\N{MINUS SIGN}\N{PRIME}" + r"])+)"
_SCRIPT_PASSES: Final[tuple[tuple[re.Pattern[str], ScriptPosition], ...]] = (
    (re.compile(rf"(?<![~\\])~{_SCRIPT_TEXT}~(?!~)"), "subscript"),
    (re.compile(rf"(?<![\[^\\])\^{_SCRIPT_TEXT}\^(?!\^)"), "superscript"),
)
_STYLE_PASSES: Final[tuple[tuple[re.Pattern[str], StyleName], ...]] = (
    (re.compile(r"\*\*([^*]+)\*\*"), "bold"),
    (re.compile(r"(?<![\w+])\+\+([^\s+](?:[^+]*[^\s+])?)\+\+(?![\w+])"), "underline"),
    (re.compile(r"~~([^~]+)~~"), "strike"),
    (re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"), "italic"),
)


@dataclass(frozen=True)
class RichContext:
    reference_numbers: Mapping[str, int] | None = None
    reference_urls: Mapping[str, str | None] = field(default_factory=dict[str, "str | None"])
    anchor_ids: frozenset[str] | None = None


class _Stash:
    def __init__(self) -> None:
        self.runs: list[Run] = []

    def set_aside(self, run: Run) -> str:
        self.runs.append(run)
        return f"\x00{len(self.runs) - 1}\x00"

    def runs_in(self, fragment: str) -> Rich:
        runs: list[Run] = []
        position = 0
        for match in _SENTINEL.finditer(fragment):
            if match.start() > position:
                runs.append(Plain(fragment[position : match.start()]))
            runs.append(self.runs[int(match.group(1))])
            position = match.end()
        if position < len(fragment):
            runs.append(Plain(fragment[position:]))
        return tuple(runs)


class _LinkTargets:
    def __init__(self) -> None:
        self.targets: list[str] = []

    def set_aside(self, fragment: str) -> str:
        return _LINK_TARGET.sub(self._set_aside_one, fragment)

    def restored(self, fragment: str) -> str:
        return _LINK_TARGET_MARK.sub(lambda match: self.targets[int(match.group(1))], fragment)

    def _set_aside_one(self, match: re.Match[str]) -> str:
        self.targets.append(match.group(0))
        return f"\x01{len(self.targets) - 1}\x01"


def _invalid_placeholder(name: str) -> ReportError:
    if "\x00" in name:
        return ReportError(
            "invalid placeholder: a {{…}} blank is a bare name (letters, digits, '_' or '-'), so it "
            "can't contain a link, `code` span, or [^citation]"
        )
    return ReportError(
        "invalid placeholder '{{" + name + "}}': a placeholder name is letters, digits, '_' or "
        "'-' only (a fill-me-later blank is written {{name}}; for a literal {{ use a `code` span)"
    )


def _anchor_holding_markup(url: str) -> ReportError:
    return ReportError(
        f"rich text links to the anchor '{url.split(chr(0), 1)[0]}…', whose target holds a `code` span or "
        "[^citation]; an anchor link targets a heading or section id"
    )


def parse_rich(text: str, context: RichContext | None = None) -> Rich:
    rules = context if context is not None else RichContext()
    stash = _Stash()
    link_targets = _LinkTargets()
    staged = _MATH_OR_CODE_SPAN.sub(partial(_set_aside_math_or_code, stash), _without_set_aside_markers(text))

    def cite(match: re.Match[str]) -> str:
        key = match.group(1)
        if rules.reference_numbers is None or key not in rules.reference_numbers:
            return match.group(0)
        return stash.set_aside(Citation(key, rules.reference_numbers[key], rules.reference_urls.get(key)))

    def anchor(match: re.Match[str], label: Rich, url: str) -> str:
        if rules.anchor_ids is None:
            return match.group(0)
        if "\x00" in url:
            raise _anchor_holding_markup(url)
        if url[1:] not in rules.anchor_ids:
            raise ReportError(
                f"rich text links to unknown anchor '{url}' — no heading or section has that id"
            )
        return stash.set_aside(AnchorLink(label, url[1:]))

    def link(match: re.Match[str]) -> str:
        label, url = stash.runs_in(match.group(1)), match.group(2)
        if url.startswith("#"):
            return anchor(match, label, url)
        if "\x00" not in url and url.startswith(ALLOWED_URL_SCHEMES):
            return stash.set_aside(Link(label, url))
        return match.group(0)

    staged = link_targets.set_aside(_FOOTNOTE.sub(cite, staged))
    staged = _ATTRIBUTE_SPAN.sub(partial(_set_aside_tint, stash), staged)
    _refuse_stray_attribute_list(staged, link_targets)
    staged = _LINK.sub(link, link_targets.restored(staged))
    return _parse_styles(_set_aside_placeholders_and_scripts(stash, staged), 0, stash)


def _set_aside_placeholders_and_scripts(stash: _Stash, fragment: str) -> str:
    staged = _PLACEHOLDER.sub(partial(_set_aside_placeholder, stash), fragment)
    for pattern, position in _SCRIPT_PASSES:
        staged = pattern.sub(partial(_set_aside_script, stash, position), staged)
    return staged


def _set_aside_placeholder(stash: _Stash, match: re.Match[str]) -> str:
    name = match.group(1)
    if "\x00" in name or not _PLACEHOLDER_NAME.fullmatch(name):
        raise _invalid_placeholder(name)
    return stash.set_aside(Placeholder(name))


def _without_set_aside_markers(text: str) -> str:
    for marker in _SET_ASIDE_MARKERS:
        text = text.replace(marker, "")
    return text


def _refuse_stray_attribute_list(staged: str, link_targets: _LinkTargets) -> None:
    stray = _STRAY_ATTRIBUTE_LIST.search(staged)
    if not stray:
        return
    attributes = stray.group(1)
    token = _attribute_token(_SENTINEL.sub("…", link_targets.restored(attributes)))
    if _LINK_TARGET_MARKER in attributes:
        raise ReportError(
            f"the attribute list {token} holds a link: an attribute list holds only key=value attributes, "
            "as in {tone=info bg=warning}"
        )
    if _STASH_MARKER in attributes:
        raise ReportError(
            f"the attribute list {token} holds other markup, such as a `code` span, math, a [^citation] or "
            "a colored [text]{…} span: an attribute list holds only key=value attributes, as in "
            "{tone=info bg=warning}"
        )
    raise ReportError(
        f"the attribute list {token} follows no [text] it can color: the text inside a [text]{{…}} span "
        "is not empty and holds no link and no other [ or ]"
    )


def _attribute_token(attributes: str) -> str:
    return "{" + attributes.strip() + "}"


def _set_aside_math_or_code(stash: _Stash, match: re.Match[str]) -> str:
    math, code = match.group(1), match.group(2)
    if math is None:
        return stash.set_aside(Code(code))
    expression = math.strip()
    refuse_invalid_math(expression, "inline")
    return stash.set_aside(InlineMath(expression))


def _set_aside_script(stash: _Stash, position: ScriptPosition, match: re.Match[str]) -> str:
    return stash.set_aside(ScriptText(position, match.group(1)))


def _set_aside_tint(stash: _Stash, match: re.Match[str]) -> str:
    tones = _span_tones(match.group(2))
    label = _parse_styles(_set_aside_placeholders_and_scripts(stash, match.group(1)), 0, stash)
    return stash.set_aside(Tinted(tones.tone, tones.background, label))


@dataclass(frozen=True)
class _SpanTones:
    tone: ToneLiteral | None
    background: ToneLiteral | None


def _span_tones(attributes: str) -> _SpanTones:
    token = _attribute_token(attributes)
    tones: dict[str, ToneLiteral] = {}
    for attribute in attributes.split():
        key, equals, value = attribute.partition("=")
        if not equals:
            raise ReportError(
                f"malformed attribute '{attribute}' in {token}: write each attribute as key=value, "
                "with no spaces around '='"
            )
        if key not in _SPAN_ATTRIBUTES:
            raise ReportError(
                f"unknown attribute '{key}' in {token}: a [text]{{…}} span takes tone=<tone> and bg=<tone>"
            )
        if key in tones:
            raise ReportError(f"attribute '{key}' is set twice in {token}")
        tones[key] = _span_tone(value, token)
    return _SpanTones(tones.get("tone"), tones.get("bg"))


def _span_tone(value: str, token: str) -> ToneLiteral:
    try:
        return _TONE.validate_python(value)
    except ValidationError as error:
        raise ReportError(
            f"unknown tone '{value}' in {token}: a tone is one of {', '.join(get_args(ToneLiteral))}, "
            f"or a palette name {', '.join(_PALETTE_ONLY_NAMES)}"
        ) from error


def _parse_styles(fragment: str, pass_index: int, stash: _Stash) -> Rich:
    if pass_index == len(_STYLE_PASSES):
        return stash.runs_in(fragment)
    pattern, style = _STYLE_PASSES[pass_index]

    def emphasise(match: re.Match[str]) -> str:
        return stash.set_aside(Styled(style, _parse_styles(match.group(1), pass_index + 1, stash)))

    return _parse_styles(pattern.sub(emphasise, fragment), pass_index + 1, stash)


class RunWriter(Protocol):
    def text(self, text: str, /) -> str: ...

    def code(self, text: str, /) -> str: ...

    def link(self, label: str, url: str, /) -> str: ...

    def anchor_link(self, label: str, anchor: str, /) -> str: ...

    def citation(self, run: Citation, /) -> str: ...

    def placeholder(self, name: str, /) -> str: ...

    def styled(self, style: StyleName, inner: str, /) -> str: ...

    def script(self, position: ScriptPosition, text: str, /) -> str: ...

    def tinted(self, tone: ToneLiteral | None, background: ToneLiteral | None, inner: str, /) -> str: ...

    def math(self, expression: str, /) -> str: ...


def write_run(run: Run, writer: RunWriter) -> str:
    match run:
        case Plain():
            return writer.text(run.text)
        case Code():
            return writer.code(run.text)
        case Link():
            return writer.link(write_runs(run.label, writer), run.url)
        case AnchorLink():
            return writer.anchor_link(write_runs(run.label, writer), run.anchor)
        case Citation():
            return writer.citation(run)
        case Placeholder():
            return writer.placeholder(run.name)
        case Styled():
            return writer.styled(run.style, write_runs(run.runs, writer))
        case ScriptText():
            return writer.script(run.position, run.text)
        case Tinted():
            return writer.tinted(run.tone, run.background, write_runs(run.runs, writer))
        case InlineMath():
            return writer.math(run.expression)
        case _:
            assert_never(run)


def write_runs(runs: Rich, writer: RunWriter) -> str:
    return "".join(write_run(run, writer) for run in runs)


class VisibleText:
    def text(self, text: str, /) -> str:
        return text

    def code(self, text: str, /) -> str:
        return text

    def link(self, label: str, _url: str, /) -> str:
        return label

    def anchor_link(self, label: str, _anchor: str, /) -> str:
        return label

    def citation(self, run: Citation, /) -> str:
        return f"[{run.number}]"

    def placeholder(self, name: str, /) -> str:
        return name

    def styled(self, _style: StyleName, inner: str, /) -> str:
        return inner

    def script(self, _position: ScriptPosition, text: str, /) -> str:
        return text

    def tinted(self, _tone: ToneLiteral | None, _background: ToneLiteral | None, inner: str, /) -> str:
        return inner

    def math(self, expression: str, /) -> str:
        return expression


def visible_text(runs: Rich) -> str:
    return write_runs(runs, VisibleText())


def _string_fields(value: object, path: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield ".".join(path), value
    elif isinstance(value, dict):
        for key, item in cast("dict[str, object]", value).items():
            yield from _string_fields(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(cast("list[object]", value)):
            yield from _string_fields(item, (*path, str(index)))


def located_rich_text_error(report: Report, text: str, error: ReportError) -> ReportError:
    fields = _string_fields(report.model_dump(mode="json"), ())
    field = next((path for path, value in fields if text in value), None)
    return ReportError(f"{field}: {error}" if field else str(error))
