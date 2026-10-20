import sys
from uuid import UUID

import pytest

from skaldr.auth import cli as auth_cli
from skaldr.auth import templates
from skaldr.auth.store import stored_notion_sign_ins
from skaldr.auth.templates import notion_templates, save_notion_template
from tests.factories.auth_factory import (
    OTHER_WORKSPACE_ID,
    WORKSPACE_ID,
    FakeBrowser,
    InMemoryKeyring,
    approving,
    free_port,
    legacy_entry_json,
    make_notion_credentials,
    seed_notion,
)
from tests.factories.notion_factory import InMemoryNotion

TEMPLATE_PAGE = "aabbccddeeff00112233445566778899"
OTHER_TEMPLATE_PAGE = "00112233445566778899aabbccddeeff"
TEMPLATE_LINK = f"https://www.notion.so/Page-Template-{TEMPLATE_PAGE}"
WORKSPACE = UUID(WORKSPACE_ID)
OTHER_WORKSPACE = UUID(OTHER_WORKSPACE_ID)
FULL_WIDTH_NOTICE = (
    "Turn on Full width or Small text on the template page in Notion yourself: skaldr cannot set or read "
    "them, and pages created from the template keep them.\n"
)
LATER = "Set it later with `skaldr auth template notion <link>`."


def _notion(template_markdown: str = "") -> InMemoryNotion:
    notion = InMemoryNotion()
    notion.add_page(TEMPLATE_PAGE, "Page template", template_markdown)
    notion.add_page(OTHER_TEMPLATE_PAGE, "Another template", "")
    return notion


def _signed_in() -> None:
    seed_notion(make_notion_credentials())


def _signed_in_to_two_workspaces() -> None:
    seed_notion(make_notion_credentials())
    seed_notion(make_notion_credentials(workspace_id=OTHER_WORKSPACE_ID, workspace_name="Other Workspace"))


def _paths(notion: InMemoryNotion) -> list[tuple[str, str]]:
    return [(request.method, request.url.path) for request in notion.requests]


@pytest.mark.parametrize(
    "link",
    [
        pytest.param(TEMPLATE_LINK, id="page-url"),
        pytest.param(TEMPLATE_PAGE, id="bare-id"),
        pytest.param("aabbccdd-eeff-0011-2233-445566778899", id="dashed-id"),
    ],
)
def test_the_template_command_checks_the_page_and_stores_it_for_the_workspace(
    link: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _signed_in()
    notion = _notion()

    exit_code = auth_cli.main(["template", "notion", link], transport=notion.mock())

    assert (exit_code, notion_templates(), _paths(notion), capsys.readouterr().out) == (
        0,
        {WORKSPACE_ID: TEMPLATE_PAGE},
        [("GET", f"/v1/pages/{TEMPLATE_PAGE}"), ("GET", f"/v1/pages/{TEMPLATE_PAGE}/markdown")],
        f"Notion workspace Example Workspace: new pages are created from template page {TEMPLATE_PAGE}.\n"
        f"{FULL_WIDTH_NOTICE}",
    )


def test_the_template_command_replaces_the_template_of_the_workspace() -> None:
    _signed_in()
    save_notion_template(WORKSPACE, OTHER_TEMPLATE_PAGE)

    exit_code = auth_cli.main(["template", "notion", TEMPLATE_LINK], transport=_notion().mock())

    assert (exit_code, notion_templates()) == (0, {WORKSPACE_ID: TEMPLATE_PAGE})


def test_the_template_command_refuses_something_that_is_not_a_notion_page_without_calling_notion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _signed_in()
    notion = _notion()

    exit_code = auth_cli.main(["template", "notion", "https://example.com/page"], transport=notion.mock())

    assert (exit_code, notion.requests, notion_templates(), capsys.readouterr().err) == (
        1,
        [],
        {},
        "error: 'https://example.com/page' is not a Notion page URL (notion.so, notion.site, notion.com) or "
        "a page id\n",
    )


def test_the_template_command_refuses_a_page_that_is_not_empty_and_keeps_the_template_it_had(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _signed_in()
    save_notion_template(WORKSPACE, OTHER_TEMPLATE_PAGE)

    exit_code = auth_cli.main(
        ["template", "notion", TEMPLATE_LINK], transport=_notion("## Boilerplate\n").mock()
    )

    assert (exit_code, notion_templates(), capsys.readouterr().err) == (
        1,
        {WORKSPACE_ID: OTHER_TEMPLATE_PAGE},
        f"error: the Notion template page {TEMPLATE_PAGE} is not empty, so Notion would copy its content "
        "into every page skaldr creates from it; empty the page in Notion, or choose another template page\n",
    )


def test_the_template_command_refuses_a_page_the_sign_in_cannot_read(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _signed_in()

    exit_code = auth_cli.main(["template", "notion", TEMPLATE_LINK], transport=InMemoryNotion().mock())

    assert (exit_code, notion_templates(), capsys.readouterr().err) == (
        1,
        {},
        f"error: the Notion template page {TEMPLATE_PAGE} cannot be read: it does not exist, or it is not "
        "shared with the connection skaldr signs in with; share the page with the connection in Notion, or "
        "choose another template page\n",
    )


def test_the_template_command_without_a_sign_in_says_to_sign_in(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = auth_cli.main(["template", "notion", TEMPLATE_LINK], transport=_notion().mock())

    assert (exit_code, capsys.readouterr().err) == (
        1,
        "error: Not signed in to Notion; run `skaldr auth notion`\n",
    )


def test_the_template_command_with_several_workspaces_asks_which_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _signed_in_to_two_workspaces()
    notion = _notion()

    exit_code = auth_cli.main(["template", "notion", TEMPLATE_LINK], transport=notion.mock())

    assert (exit_code, notion.requests, notion_templates(), capsys.readouterr().err) == (
        1,
        [],
        {},
        "error: Signed in to several Notion workspaces (Example Workspace "
        f"({WORKSPACE_ID}), Other Workspace ({OTHER_WORKSPACE_ID})); name one with --workspace\n",
    )


@pytest.mark.parametrize("selector", ["Other Workspace", OTHER_WORKSPACE_ID])
def test_the_template_command_sets_the_template_of_the_workspace_named_with_workspace(
    selector: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _signed_in_to_two_workspaces()

    exit_code = auth_cli.main(
        ["template", "notion", TEMPLATE_LINK, "--workspace", selector], transport=_notion().mock()
    )

    assert (exit_code, notion_templates()) == (0, {OTHER_WORKSPACE_ID: TEMPLATE_PAGE})
    assert capsys.readouterr().out.startswith(
        f"Notion workspace Other Workspace: new pages are created from template page {TEMPLATE_PAGE}.\n"
    )


def test_the_template_command_names_a_workspace_that_is_not_signed_in(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _signed_in()

    exit_code = auth_cli.main(
        ["template", "notion", TEMPLATE_LINK, "--workspace", "Missing Workspace"], transport=_notion().mock()
    )

    assert (exit_code, capsys.readouterr().err) == (
        1,
        "error: Not signed in to Notion workspace Missing Workspace; run `skaldr auth notion`\n",
    )


def test_a_sign_in_without_a_workspace_id_cannot_hold_a_template(
    keychain: InMemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    keychain.entries[("skaldr", "notion")] = legacy_entry_json(make_notion_credentials())
    notion = _notion()

    exit_code = auth_cli.main(["template", "notion", TEMPLATE_LINK], transport=notion.mock())

    assert (exit_code, notion.requests, notion_templates(), capsys.readouterr().err) == (
        1,
        [],
        {},
        "error: The Notion sign-in for workspace Example Workspace has no workspace id, so it cannot hold a "
        "template; run `skaldr auth notion` again\n",
    )


def test_the_template_command_clears_only_the_template_of_the_workspace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _signed_in_to_two_workspaces()
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)
    save_notion_template(OTHER_WORKSPACE, OTHER_TEMPLATE_PAGE)

    exit_code = auth_cli.main(["template", "notion", "--clear", "--workspace", WORKSPACE_ID])

    assert (exit_code, notion_templates(), capsys.readouterr().out) == (
        0,
        {OTHER_WORKSPACE_ID: OTHER_TEMPLATE_PAGE},
        "Cleared the page template of Notion workspace Example Workspace.\n",
    )


def test_clearing_a_workspace_without_a_template_says_there_is_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _signed_in()

    exit_code = auth_cli.main(["template", "notion", "--clear"])

    assert (exit_code, capsys.readouterr().out) == (
        0,
        "Notion workspace Example Workspace has no page template.\n",
    )


def test_the_template_command_takes_a_link_or_clear_but_not_both(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        auth_cli.main(["template", "notion", TEMPLATE_LINK, "--clear"])

    assert (raised.value.code, capsys.readouterr().err.splitlines()[-1]) == (
        2,
        "skaldr auth template: error: argument --clear: not allowed with argument link",
    )


def test_the_template_command_without_a_link_shows_the_template_of_each_workspace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _signed_in_to_two_workspaces()
    save_notion_template(OTHER_WORKSPACE, OTHER_TEMPLATE_PAGE)

    exit_code = auth_cli.main(["template", "notion"])

    assert (exit_code, capsys.readouterr().out) == (
        0,
        f"Notion workspace Example Workspace (id {WORKSPACE_ID}): no page template\n"
        f"Notion workspace Other Workspace (id {OTHER_WORKSPACE_ID}): page template {OTHER_TEMPLATE_PAGE}\n",
    )


def test_the_template_command_shows_the_template_of_the_workspace_named_with_workspace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _signed_in_to_two_workspaces()
    save_notion_template(WORKSPACE, TEMPLATE_PAGE)

    exit_code = auth_cli.main(["template", "notion", "--workspace", "Example Workspace"])

    assert (exit_code, capsys.readouterr().out) == (
        0,
        f"Notion workspace Example Workspace (id {WORKSPACE_ID}): page template {TEMPLATE_PAGE}\n",
    )


def test_showing_the_template_without_a_sign_in_says_to_sign_in(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = auth_cli.main(["template", "notion"])

    assert (exit_code, capsys.readouterr().out) == (0, "Not signed in to Notion.\n")


def test_status_shows_the_template_of_each_workspace_that_has_one(capsys: pytest.CaptureFixture[str]) -> None:
    _signed_in_to_two_workspaces()
    save_notion_template(OTHER_WORKSPACE, OTHER_TEMPLATE_PAGE)

    exit_code = auth_cli.main(["status"])

    assert (exit_code, capsys.readouterr().out.splitlines()[:2]) == (
        0,
        [
            f"notion  signed in to workspace Example Workspace (id {WORKSPACE_ID}) (keychain)",
            f"notion  signed in to workspace Other Workspace (id {OTHER_WORKSPACE_ID}) (keychain), "
            f"page template {OTHER_TEMPLATE_PAGE}",
        ],
    )


def test_status_still_lists_the_sign_ins_when_the_template_file_is_unreadable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _signed_in()
    templates.template_file().write_text("not json", encoding="utf-8")

    exit_code = auth_cli.main(["status"])

    assert (exit_code, capsys.readouterr().out.splitlines()[:2]) == (
        1,
        [
            f"notion  signed in to workspace Example Workspace (id {WORKSPACE_ID}) (keychain)",
            f"notion  error: The file {templates.template_file()} that holds the Notion page templates is "
            "unreadable; fix it or remove it, then set the template again with `skaldr auth template notion "
            "<link>`",
        ],
    )


class _Terminal:
    def isatty(self) -> bool:
        return True


def _sign_in_asking(
    monkeypatch: pytest.MonkeyPatch, notion: InMemoryNotion, answers: list[str]
) -> tuple[int, list[str]]:
    monkeypatch.setenv("NOTION_CLIENT_ID", "client-id")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(sys, "stdin", _Terminal())
    asked: list[str] = []

    def answer(prompt: str) -> str:
        asked.append(prompt)
        reply = answers.pop(0)
        if reply == "EOF":
            raise EOFError
        if reply == "INTERRUPT":
            raise KeyboardInterrupt
        return reply

    monkeypatch.setattr("builtins.input", answer)
    browser = FakeBrowser(approving)
    exit_code = auth_cli.main(
        ["notion", "--port", str(free_port())], transport=notion.mock(), open_browser=browser
    )
    browser.finished()
    return exit_code, asked


PROMPT = "Notion page template link (Enter to skip): "
EXPLANATION = (
    "A page template makes the pages skaldr creates keep the template page's Full width or Small text. "
    "It must be an empty page shared with your connection.\n"
)


def test_signing_in_to_notion_offers_a_template_and_stores_the_one_given(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, asked = _sign_in_asking(monkeypatch, _notion(), [TEMPLATE_LINK])

    assert (exit_code, asked, notion_templates()) == (0, [PROMPT], {WORKSPACE_ID: TEMPLATE_PAGE})
    assert capsys.readouterr().out.splitlines()[-4:] == [
        "Signed in to Notion workspace Example Workspace. Saved to the keychain.",
        EXPLANATION.rstrip("\n"),
        f"Notion workspace Example Workspace: new pages are created from template page {TEMPLATE_PAGE}.",
        FULL_WIDTH_NOTICE.rstrip("\n"),
    ]


def test_pressing_enter_at_the_template_question_skips_it_and_asks_nothing_of_notion(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    notion = _notion()

    exit_code, asked = _sign_in_asking(monkeypatch, notion, [""])

    assert (exit_code, asked, notion_templates(), _paths(notion)) == (
        0,
        [PROMPT],
        {},
        [("POST", "/v1/oauth/token")],
    )
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "Signed in to Notion workspace Example Workspace. Saved to the keychain.",
        EXPLANATION.rstrip("\n"),
    ]


def test_a_template_link_that_does_not_check_out_leaves_the_sign_in_saved_and_says_how_to_set_it_later(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, _ = _sign_in_asking(monkeypatch, _notion("## Boilerplate\n"), [TEMPLATE_LINK])

    assert (exit_code, notion_templates(), _stored_workspaces()) == (0, {}, [WORKSPACE_ID])
    assert capsys.readouterr().err == (
        f"warning: the page template was not set: the Notion template page {TEMPLATE_PAGE} is not empty, so "
        "Notion would copy its content into every page skaldr creates from it; empty the page in Notion, or "
        f"choose another template page. {LATER}\n"
    )


def test_something_that_is_not_a_notion_page_at_the_template_question_is_reported_without_failing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, _ = _sign_in_asking(monkeypatch, _notion(), ["https://example.com/page"])

    assert (exit_code, notion_templates(), capsys.readouterr().err) == (
        0,
        {},
        "warning: the page template was not set: 'https://example.com/page' is not a Notion page URL "
        f"(notion.so, notion.site, notion.com) or a page id. {LATER}\n",
    )


@pytest.mark.parametrize("reply", ["EOF", "INTERRUPT"])
def test_giving_up_at_the_template_question_keeps_the_sign_in_and_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    exit_code, _ = _sign_in_asking(monkeypatch, _notion(), [reply])

    assert (exit_code, notion_templates(), _stored_workspaces()) == (0, {}, [WORKSPACE_ID])


def test_signing_in_to_notion_without_a_terminal_does_not_ask_for_a_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTION_CLIENT_ID", "client-id")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "client-secret")

    def refuse(prompt: str) -> str:
        pytest.fail(f"prompted for {prompt!r}")

    monkeypatch.setattr("builtins.input", refuse)
    browser = FakeBrowser(approving)

    exit_code = auth_cli.main(
        ["notion", "--port", str(free_port())], transport=_notion().mock(), open_browser=browser
    )

    assert (exit_code, browser.finished(), notion_templates()) == (0, [200], {})


def _stored_workspaces() -> list[str]:
    return [str(entry.credentials.workspace_id) for entry in stored_notion_sign_ins() if entry.credentials]
