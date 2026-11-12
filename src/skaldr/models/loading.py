import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, NamedTuple, cast

import yaml
from pydantic import TypeAdapter, ValidationError

from skaldr.errors import ReportError
from skaldr.models.containers import BUILT_BY_AN_INDEX, PageBlock
from skaldr.models.meta import Badge, Person, PersonKey
from skaldr.models.parsing import format_validation_error, parse_report, read_text_file
from skaldr.models.report import Index, Report

# Non-cyclic depth cap: cycles are already caught by `ancestors`, but a pathological non-cyclic chain
# would recurse until Python's own recursion limit and surface as a raw RecursionError. Every other
# load failure is a ReportError, so cap the depth to keep that contract. Real docs never nest this far.
_MAX_INCLUDE_DEPTH = 50

_MAX_ALIASES = 10_000

_MAX_FILES = 1_000

_GITDIR_LINE_START: Final = b"gitdir:"


class _TooManyAliasesError(Exception):
    pass


class _TooManyFilesError(Exception):
    pass


class _IncludeRoot(NamedTuple):
    folder: Path
    kind: Literal["git work tree", "folder"]


@dataclass
class _LoadScope:
    root: _IncludeRoot
    files_read: int = 0
    aliases_seen: int = 0

    def read_a_file(self) -> None:
        self.files_read += 1
        if self.files_read > _MAX_FILES:
            raise _TooManyFilesError

    def see_an_alias(self) -> None:
        self.aliases_seen += 1
        if self.aliases_seen > _MAX_ALIASES:
            raise _TooManyAliasesError


class _AliasBoundedLoader(yaml.SafeLoader):
    scope: _LoadScope

    def compose_node(self, parent: yaml.Node | None, index: int) -> yaml.Node | None:
        if self.check_event(yaml.AliasEvent):  # pyright: ignore[reportUnknownMemberType]
            self.scope.see_an_alias()
        return super().compose_node(parent, index)


def _is_git_marker(folder: Path) -> bool:
    marker = folder / ".git"
    if marker.is_dir():
        return True
    if not marker.is_file():
        return False
    try:
        with marker.open("rb") as opened:
            return opened.read(len(_GITDIR_LINE_START)) == _GITDIR_LINE_START
    except OSError:
        return False


def _load_scope(document: Path) -> _LoadScope:
    try:
        own_folder = document.parent.resolve()
    except (OSError, RuntimeError) as err:
        raise ReportError(f"could not resolve {document}: {err}") from err
    for folder in (own_folder, *own_folder.parents):
        if _is_git_marker(folder):
            return _LoadScope(_IncludeRoot(folder, "git work tree"))
    return _LoadScope(_IncludeRoot(own_folder, "folder"))


def _refuse_an_include_outside(root: _IncludeRoot, includer: Path, target: str) -> Path:
    included = includer.parent / target
    try:
        resolved = included.resolve()
    except (OSError, RuntimeError) as err:
        raise ReportError(f"could not resolve {included}: {err}") from err
    if not resolved.is_relative_to(root.folder):
        raise ReportError(
            f"!include {target} in {includer} resolves to {resolved}, outside {root.folder}, "
            f"the {root.kind} that holds the document"
        )
    return included


def _load_yaml_with_includes(
    path: Path,
    ancestors: tuple[Path, ...],
    loaded: list[Path],
    text: str | None = None,
    scope: _LoadScope | None = None,
) -> Any:
    """Parse a YAML file, resolving `!include <relative-path>` tags by splicing in the parsed content
    of the referenced file. Paths resolve relative to the *including* file's directory (not the cwd),
    so a fragment set can move as a unit. `ancestors` is the chain of files currently being loaded —
    a resolved path reappearing in it is a cycle and raises rather than recursing forever."""
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as err:  # RuntimeError: a symlink loop while resolving
        raise ReportError(f"could not resolve {path}: {err}") from err
    if resolved in ancestors:
        chain = " -> ".join(str(ancestor) for ancestor in (*ancestors, resolved))
        raise ReportError(f"circular !include: {chain}")
    if len(ancestors) >= _MAX_INCLUDE_DEPTH:
        raise ReportError(f"!include nested more than {_MAX_INCLUDE_DEPTH} deep at {path}, likely a mistake")
    load_scope = scope if scope is not None else _load_scope(path)
    try:
        load_scope.read_a_file()
    except _TooManyFilesError as err:
        raise ReportError(
            f"the document reads more than {_MAX_FILES} files through !include, reaching {path}; no real "
            "document needs that many, and a fan-out of includes is how an include bomb is built"
        ) from err
    if text is None:
        text = read_text_file(path)
    loaded.append(resolved)

    class _IncludeLoader(_AliasBoundedLoader):
        """SafeLoader subclass — `!include` scoped to this file's dir; keeps `yaml.load` safe."""

        scope = load_scope

    def _construct_include(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
        if not isinstance(node, yaml.ScalarNode):
            raise ReportError(f"!include in {path} takes a single file path, not a list or mapping")
        target = str(loader.construct_scalar(node)).strip()
        if not target:
            raise ReportError(f"!include in {path} needs a file path")
        if Path(target).is_absolute():
            raise ReportError(f"!include in {path} must be a relative path, not absolute: {target}")
        included = _refuse_an_include_outside(load_scope.root, path, target)
        return _load_yaml_with_includes(included, (*ancestors, resolved), loaded, scope=load_scope)

    _IncludeLoader.add_constructor("!include", _construct_include)
    try:
        return yaml.load(text, Loader=_IncludeLoader)
    except yaml.YAMLError as err:
        raise ReportError(f"invalid YAML in {path}: {err}") from err
    except RecursionError as err:
        raise ReportError(f"{path} nests too deeply or refers to itself") from err
    except _TooManyAliasesError as err:
        raise ReportError(
            f"{path} uses more than {_MAX_ALIASES} YAML aliases, counting every file it includes; "
            "no real document needs that many, and a flood of them is how a YAML bomb is built"
        ) from err


def _index_of(data: object) -> object:
    return cast("Mapping[str, object]", data).get("index") if isinstance(data, Mapping) else None


class _LoadedPart(NamedTuple):
    path: Path
    data: Mapping[str, Any]
    report: Report


def _parsed_index(data: object) -> Index:
    try:
        return Index.model_validate(data)
    except ValidationError as err:
        raise ReportError(format_validation_error(err, ("index",))) from err


def _part_file(index_path: Path, part_path: str) -> Path:
    part = index_path.parent / part_path
    try:
        resolved, folder = part.resolve(), index_path.parent.resolve()
    except (OSError, RuntimeError) as err:
        raise ReportError(f"could not resolve {part}: {err}") from err
    if not resolved.is_relative_to(folder):
        raise ReportError(
            f"part {part_path} resolves to {resolved}, outside the index file's folder {folder}"
        )
    return part


def _loaded_part(path: Path, scope: _LoadScope) -> _LoadedPart:
    data = _load_yaml_with_includes(path, (), [], scope=scope)
    if isinstance(_index_of(data), Mapping):
        raise ReportError(f"part {path} is itself an index; an index lists document files, not other indexes")
    try:
        report = parse_report(data)
    except ReportError as err:
        raise ReportError(f"in part {path}: {err}") from err
    return _LoadedPart(path, cast("Mapping[str, Any]", data), report)


_BADGES: Final = TypeAdapter(dict[str, Badge])


def _parsed_badges(data: object) -> dict[str, Badge]:
    try:
        return _BADGES.validate_python(data)
    except ValidationError as err:
        raise ReportError(format_validation_error(err, ("badges",))) from err


def _merged_badges(declared: Sequence[tuple[Path, Mapping[str, Badge]]]) -> dict[str, Any]:
    merged: dict[str, Badge] = {}
    declared_in: dict[str, Path] = {}
    for path, badges in declared:
        for key, badge in badges.items():
            if key in merged and merged[key] != badge:
                raise ReportError(
                    f"badge {key!r} is declared differently in {declared_in[key]} and {path}; "
                    "an index merges every part's badges, "
                    "so give it one label, tone and legend or rename one key"
                )
            merged.setdefault(key, badge)
            declared_in.setdefault(key, path)
    return {key: badge.model_dump(mode="json") for key, badge in merged.items()}


_PEOPLE: Final = TypeAdapter(dict[PersonKey, Person])


def _own_meta_value(data: Mapping[str, Any], name: str) -> object:
    meta: object = data.get("meta")
    return cast("Mapping[str, object]", meta).get(name) if isinstance(meta, Mapping) else None


def _parsed_people(data: object) -> dict[str, Person]:
    try:
        return _PEOPLE.validate_python({} if data is None else data)
    except ValidationError as err:
        raise ReportError(format_validation_error(err, ("meta", "people"))) from err


def _merged_people(declared: Sequence[tuple[Path, Mapping[str, Person]]]) -> dict[str, Any]:
    merged: dict[str, Person] = {}
    declared_in: dict[str, Path] = {}
    for path, people in declared:
        for key, person in people.items():
            if key in merged and merged[key] != person:
                raise ReportError(
                    f"person {key!r} is declared differently in {declared_in[key]} and {path}; "
                    "an index merges every part's people, so give it one Notion, Jira and Slack id "
                    "or rename one key"
                )
            merged.setdefault(key, person)
            declared_in.setdefault(key, path)
    return {key: person.model_dump(mode="json") for key, person in merged.items()}


def _merged_jira_site(declared: Sequence[tuple[Path, object]]) -> str | None:
    first: tuple[Path, str] | None = None
    for path, site in declared:
        if not isinstance(site, str):
            continue
        address = site.rstrip("/")
        if first is None:
            first = (path, address)
        elif first[1] != address:
            raise ReportError(
                f"jira_site is declared differently in {first[0]} and {path}; "
                "an index points every issue link at one site, so give each part the same address"
            )
    return first[1] if first else None


def _merged_index_meta(path: Path, data: Mapping[str, Any], parts: Sequence[_LoadedPart]) -> object:
    meta: object = data.get("meta")
    if not isinstance(meta, Mapping):
        return meta
    people = _merged_people(
        [
            (path, _parsed_people(_own_meta_value(data, "people"))),
            *((part.path, part.report.meta.people) for part in parts),
        ]
    )
    site = _merged_jira_site(
        [
            (path, _own_meta_value(data, "jira_site")),
            *((part.path, part.report.meta.jira_site) for part in parts),
        ]
    )
    return {
        **cast("Mapping[str, Any]", meta),
        **({"people": people} if people else {}),
        **({"jira_site": site} if site else {}),
    }


def _refuse_a_doc_id_published_twice(parts: Sequence[_LoadedPart]) -> None:
    first_part_with: dict[str, Path] = {}
    for part in parts:
        if part.report.publish is None:
            continue
        doc_id = part.report.publish.doc_id
        if doc_id in first_part_with:
            raise ReportError(
                f"doc_id {doc_id!r} is published by both {first_part_with[doc_id]} and {part.path}; "
                "an index needs each part's publish.doc_id to be different"
            )
        first_part_with[doc_id] = part.path


def _part_block(part: _LoadedPart, index: Index) -> dict[str, Any]:
    publish = part.report.publish
    return {
        "type": "part",
        "title": part.report.meta.title,
        "doc_id": publish.doc_id if publish else None,
        "collapsed": index.collapsed,
        "blocks": part.data["blocks"],
    }


_INTRO_BLOCKS: Final = TypeAdapter(list[PageBlock])


def _intro_blocks(data: Mapping[str, Any]) -> list[object]:
    intro: object = data.get("blocks", [])
    if isinstance(intro, list) and not intro and "blocks" in data:
        raise ReportError(
            "invalid content data: blocks: an index's `blocks` is its optional intro and needs at least "
            "one block; leave `blocks` out for no intro"
        )
    try:
        _INTRO_BLOCKS.validate_python(intro, context={BUILT_BY_AN_INDEX: False})
    except ValidationError as err:
        raise ReportError(format_validation_error(err, ("blocks",))) from err
    return cast("list[object]", intro)


class _Document(NamedTuple):
    data: object
    parts: tuple[tuple[int, Path], ...] = ()


def _combined_index(path: Path, data: Mapping[str, Any], index: Index, scope: _LoadScope) -> _Document:
    if data.get("publish") is not None:
        raise ReportError("an index document cannot carry `publish` yet; publish each part file on its own")
    intro = _intro_blocks(data)
    parts = [_loaded_part(_part_file(path, part_path), scope) for part_path in index.parts]
    _refuse_a_doc_id_published_twice(parts)
    own_badges = _parsed_badges(data.get("badges", {}))
    badges = _merged_badges([(path, own_badges), *((part.path, part.report.badges) for part in parts)])
    page = {key: value for key, value in data.items() if key != "index"}
    combined = {
        **page,
        **({"meta": _merged_index_meta(path, data, parts)} if "meta" in page else {}),
        "badges": badges,
        "blocks": [*intro, *(_part_block(part, index) for part in parts)],
    }
    return _Document(combined, tuple(enumerate((part.path for part in parts), start=len(intro))))


def _load_document(path: Path) -> _Document:
    scope = _load_scope(path)
    data = _load_yaml_with_includes(path, (), [], scope=scope)
    index = _index_of(data)
    if index is None:
        return _Document(data)
    return _combined_index(path, cast("Mapping[str, Any]", data), _parsed_index(index), scope)


_PART_PLACE = re.compile(r"\bblocks\.(\d+)\.part\b")


def _parts_named_in(message: str, parts: Sequence[tuple[int, Path]]) -> str | None:
    named = {int(position) for position in _PART_PLACE.findall(message)}
    places = [f"blocks.{position} is {path}" for position, path in parts if position in named]
    if not places:
        return None
    listed = places[0] if len(places) == 1 else f"{', '.join(places[:-1])} and {places[-1]}"
    return f"in this index, {listed}"


def load_report(path: Path) -> Report:
    report, _ = load_report_and_source(path)
    return report


def load_report_and_source(path: Path) -> tuple[Report, Any]:
    document = _load_document(path)
    try:
        return parse_report(document.data, built_by_an_index=bool(document.parts)), document.data
    except ReportError as err:
        where = _parts_named_in(str(err), document.parts)
        if where is None:
            raise
        raise ReportError(f"{err}; {where}") from err


def document_data(path: Path, text: str) -> Any:
    return _load_yaml_with_includes(path, (), [], text)


def names_an_index(data: object) -> bool:
    return _index_of(data) is not None


def content_files(path: Path) -> tuple[Path, ...]:
    loaded: list[Path] = []
    scope = _load_scope(path)
    index = _index_of(_load_yaml_with_includes(path, (), loaded, scope=scope))
    if index is not None:
        for part_path in _parsed_index(index).parts:
            _load_yaml_with_includes(_part_file(path, part_path), (), loaded, scope=scope)
    return tuple(loaded)
