import pytest
from pydantic import JsonValue

from skaldr.publish.content import (
    FIELDS,
    TITLE,
    ItemContent,
    SectionChanges,
    comparable,
    content_digest,
    differing_parts,
    placed_section,
    same_fields,
    section_changes,
    section_part,
)


@pytest.mark.parametrize(
    ("key", "text", "follows", "expected"),
    [
        pytest.param("n", "N", None, {"n": "N", "a": "A", "b": "B"}, id="added-first"),
        pytest.param("n", "N", "a", {"a": "A", "n": "N", "b": "B"}, id="added-after-a-section"),
        pytest.param("b", "B2", None, {"b": "B2", "a": "A"}, id="moved-first"),
        pytest.param("a", "A2", "b", {"b": "B", "a": "A2"}, id="moved-after-a-section"),
        pytest.param("a", None, None, {"b": "B"}, id="removed"),
        pytest.param(
            "n", "N", "gone", {"a": "A", "b": "B", "n": "N"}, id="after-a-missing-section-goes-last"
        ),
    ],
)
def test_a_section_is_placed_after_the_section_it_follows(
    key: str, text: str | None, follows: str | None, expected: dict[str, str]
) -> None:
    placed = placed_section({"a": "A", "b": "B"}, key, text, follows)

    assert list(placed.items()) == list(expected.items())


@pytest.mark.parametrize(
    ("published", "current"),
    [
        pytest.param({"labels": ["a", "b"]}, {"labels": ["b", "a"]}, id="list-order"),
        pytest.param({"labels": ["a", "a", "b"]}, {"labels": ["b", "a"]}, id="repeated-member"),
        pytest.param({"a": 1, "b": 2}, {"b": 2, "a": 1}, id="key-order"),
        pytest.param(
            {"components": [{"name": "web", "id": "2"}, {"name": "api", "id": "1"}]},
            {"components": [{"id": "1", "name": "api"}, {"id": "2", "name": "web"}]},
            id="list-of-objects",
        ),
        pytest.param({"outer": {"tags": ["y", "x"]}}, {"outer": {"tags": ["x", "y"]}}, id="nested"),
    ],
)
def test_fields_compare_as_sorted_sets_with_sorted_keys(
    published: dict[str, JsonValue], current: dict[str, JsonValue]
) -> None:
    assert same_fields(published, current) is True


@pytest.mark.parametrize(
    ("published", "current"),
    [
        pytest.param({"labels": ["a", "b"]}, {"labels": ["a", "c"]}, id="different-member"),
        pytest.param({"labels": ["a"]}, {"labels": "a"}, id="list-and-scalar"),
        pytest.param({"priority": "High"}, {}, id="missing-key"),
    ],
)
def test_fields_with_different_members_differ(
    published: dict[str, JsonValue], current: dict[str, JsonValue]
) -> None:
    assert same_fields(published, current) is False


def test_the_comparable_form_sorts_keys_and_list_members_and_drops_repeats() -> None:
    value: JsonValue = {"z": ["b", "a", "b"], "a": [{"k": 2, "j": 1}, 3]}

    assert comparable(value) == {"a": [3, {"j": 1, "k": 2}], "z": ["a", "b"]}


def test_unchanged_sections_need_no_writes() -> None:
    sections = {"a": "A\n", "b": "B\n"}

    assert section_changes(sections, dict(sections)) == SectionChanges((), ())


def test_an_added_a_changed_and_a_removed_section_are_found_in_document_order() -> None:
    old = {"a": "A\n", "b": "B\n", "c": "C\n"}
    new = {"new": "N\n", "a": "A\n", "c": "C2\n"}

    assert section_changes(old, new) == SectionChanges(written=("new", "c"), removed=("b",))


def test_a_moved_section_is_written_again_at_its_new_place() -> None:
    old = {"a": "A\n", "b": "B\n", "c": "C\n"}
    new = {"c": "C\n", "a": "A\n", "b": "B\n"}

    assert section_changes(old, new) == SectionChanges(written=("c",), removed=())


def test_the_parts_that_differ_are_the_title_the_fields_and_each_changed_section() -> None:
    published = ItemContent(title="Tools", sections={"a": "A\n", "b": "B\n"}, fields={"labels": ["x", "y"]})
    current = ItemContent(title="Garden tools", sections={"a": "A2\n"}, fields={"labels": ["y"]})

    assert differing_parts(published, current) == (TITLE, FIELDS, section_part("a"), section_part("b"))


def test_reordered_labels_are_not_a_differing_part() -> None:
    published = ItemContent(title="Tools", fields={"labels": ["x", "y"]})
    current = ItemContent(title="Tools", fields={"labels": ["y", "x"]})

    assert differing_parts(published, current) == ()


def test_the_digest_ignores_label_order_and_follows_section_text() -> None:
    first = ItemContent(title="Tools", sections={"a": "A\n"}, fields={"labels": ["x", "y"]})
    reordered = ItemContent(title="Tools", sections={"a": "A\n"}, fields={"labels": ["y", "x"]})
    edited = ItemContent(title="Tools", sections={"a": "A edited\n"}, fields={"labels": ["x", "y"]})

    assert (
        content_digest(first) == content_digest(reordered),
        content_digest(first) == content_digest(edited),
    ) == (
        True,
        False,
    )
