import json
from uuid import UUID

import pytest

from skaldr.auth import templates
from skaldr.auth.templates import (
    clear_notion_template,
    notion_template_for,
    notion_templates,
    save_notion_template,
)
from skaldr.errors import AuthError
from tests.factories.auth_factory import OTHER_WORKSPACE_ID, WORKSPACE_ID

WORKSPACE = UUID(WORKSPACE_ID)
OTHER_WORKSPACE = UUID(OTHER_WORKSPACE_ID)
TEMPLATE_PAGE = "0123456789abcdef0123456789abcdef"
OTHER_TEMPLATE_PAGE = "fedcba9876543210fedcba9876543210"


def _stored() -> object:
    return json.loads(templates.template_file().read_text(encoding="utf-8"))


def test_nothing_is_stored_before_a_template_is_set() -> None:
    assert (notion_templates(), notion_template_for(WORKSPACE), templates.template_file().exists()) == (
        {},
        None,
        False,
    )


def test_a_template_is_stored_by_workspace_id_in_a_plain_json_file() -> None:
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)

    assert (_stored(), notion_template_for(WORKSPACE), notion_template_for(OTHER_WORKSPACE)) == (
        {WORKSPACE_ID: TEMPLATE_PAGE},
        TEMPLATE_PAGE,
        None,
    )


def test_a_workspace_without_an_id_has_no_template_even_beside_an_entry_named_none() -> None:
    templates.template_file().write_text(json.dumps({"None": TEMPLATE_PAGE}), encoding="utf-8")

    assert notion_template_for(None) is None


def test_setting_a_template_for_one_workspace_keeps_the_template_of_another() -> None:
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    save_notion_template(OTHER_WORKSPACE, OTHER_TEMPLATE_PAGE)

    assert notion_templates() == {WORKSPACE_ID: TEMPLATE_PAGE, OTHER_WORKSPACE_ID: OTHER_TEMPLATE_PAGE}


def test_setting_a_template_again_replaces_the_one_before() -> None:
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    save_notion_template(WORKSPACE, OTHER_TEMPLATE_PAGE)

    assert notion_templates() == {WORKSPACE_ID: OTHER_TEMPLATE_PAGE}


def test_clearing_removes_only_that_workspaces_template_and_says_it_was_there() -> None:
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    save_notion_template(OTHER_WORKSPACE, OTHER_TEMPLATE_PAGE)

    cleared = clear_notion_template(WORKSPACE)

    assert (cleared, notion_templates()) == (True, {OTHER_WORKSPACE_ID: OTHER_TEMPLATE_PAGE})


def test_clearing_a_workspace_with_no_template_says_so_and_writes_nothing() -> None:
    cleared = clear_notion_template(WORKSPACE)

    assert (cleared, templates.template_file().exists()) == (False, False)


@pytest.mark.parametrize("unreadable", ["not json", "[]", '{"a": 1}', '{"a": ["b"]}'])
def test_a_template_file_that_is_not_a_map_of_workspace_to_page_is_refused_naming_the_file(
    unreadable: str,
) -> None:
    templates.template_file().write_text(unreadable, encoding="utf-8")

    with pytest.raises(AuthError) as caught:
        notion_templates()

    assert str(caught.value) == (
        f"The file {templates.template_file()} that holds the Notion page templates is unreadable; fix it or "
        "remove it, then set the template again with `skaldr auth template notion <link>`"
    )


def test_a_template_file_skaldr_cannot_write_is_an_auth_error_naming_the_file() -> None:
    path = templates.template_file()
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o444)

    with pytest.raises(AuthError) as caught:
        save_notion_template(WORKSPACE, TEMPLATE_PAGE)

    assert str(caught.value) == (
        f"skaldr cannot write the file {path} that holds the Notion page templates "
        f"([Errno 13] the file is read-only, so skaldr leaves it as it is: '{path.resolve()}')"
    )


def test_a_template_file_that_cannot_be_opened_is_refused_as_unreadable() -> None:
    templates.template_file().mkdir()

    with pytest.raises(AuthError, match="is unreadable"):
        notion_templates()
