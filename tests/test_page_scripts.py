import pytest

from skaldr import compute
from skaldr.models import parse_report
from skaldr.render import render_html
from tests.factories.report_factory import make_report, make_request
from tests.node_page import (
    MenuOutcome,
    PageOutcome,
    PageRun,
    call_script_function,
    requires_node,
    run_menu_steps,
    run_page_scripts,
    script_containing,
)

pytestmark = requires_node


def _page_html() -> str:
    return render_html(parse_report(make_report()))


def _boot_script(html: str) -> str:
    return script_containing(html, "function restore(")


def _boot_and_controls(html: str) -> list[str]:
    return [_boot_script(html), script_containing(html, "data-set")]


def _after_boot(run: PageRun) -> PageOutcome:
    return run_page_scripts([_boot_script(_page_html())], run)


@pytest.mark.parametrize(
    ("storage", "expected"),
    [
        pytest.param(
            {"skaldr-width": "wide"},
            PageOutcome({"data-width": "wide"}, {"skaldr-width": "wide"}),
            id="wide-is-restored",
        ),
        pytest.param(
            {"skaldr-width": "full", "skaldr-theme": "dark"},
            PageOutcome(
                {"data-width": "full", "data-theme": "dark"}, {"skaldr-width": "full", "skaldr-theme": "dark"}
            ),
            id="full-width-and-dark-theme-are-restored",
        ),
        pytest.param({}, PageOutcome({}, {}), id="nothing-stored-changes-nothing"),
        pytest.param(
            {"skaldr-width": "giant", "skaldr-theme": "sepia"},
            PageOutcome({}, {}),
            id="unknown-values-are-ignored-and-forgotten",
        ),
        pytest.param(
            {"skaldr-width": "default"},
            PageOutcome({}, {}),
            id="the-default-width-is-never-stored-so-a-stored-one-is-forgotten",
        ),
    ],
)
def test_the_boot_script_restores_only_known_values_and_forgets_the_rest(
    storage: dict[str, str], expected: PageOutcome
) -> None:
    assert _after_boot(PageRun(storage=storage)) == expected


def test_the_boot_script_survives_storage_that_throws() -> None:
    outcome = _after_boot(PageRun(storage={"skaldr-width": "wide"}, storage_throws=True))

    assert outcome == PageOutcome({}, {"skaldr-width": "wide"})


@pytest.mark.parametrize(
    ("clicks", "expected"),
    [
        pytest.param(
            (("width", "wide"),),
            PageOutcome({"data-width": "wide"}, {"skaldr-width": "wide"}),
            id="wide-is-set-and-remembered",
        ),
        pytest.param(
            (("width", "full"),),
            PageOutcome({"data-width": "full"}, {"skaldr-width": "full"}),
            id="full-is-set-and-remembered",
        ),
        pytest.param(
            (("width", "wide"), ("width", "default")),
            PageOutcome({}, {}),
            id="default-clears-the-attribute-and-forgets-the-width",
        ),
        pytest.param(
            (("theme", "dark"),),
            PageOutcome({"data-theme": "dark"}, {"skaldr-theme": "dark"}),
            id="dark-is-set-and-remembered",
        ),
        pytest.param(
            (("theme", "light"), ("theme", "auto")),
            PageOutcome({}, {}),
            id="auto-clears-the-attribute-and-forgets-the-theme",
        ),
    ],
)
def test_the_display_controls_set_and_remember_the_choice(
    clicks: tuple[tuple[str, str], ...], expected: PageOutcome
) -> None:
    assert run_page_scripts(_boot_and_controls(_page_html()), PageRun(clicks=clicks)) == expected


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        pytest.param(("click-settings",), MenuOutcome(True, False, None), id="settings-open-on-their-own"),
        pytest.param(("open-contents",), MenuOutcome(False, True, "true"), id="contents-open-on-their-own"),
        pytest.param(
            ("open-contents", "close-contents"),
            MenuOutcome(False, False, "false"),
            id="the-contents-button-reads-collapsed-once-the-panel-closes",
        ),
        pytest.param(
            ("click-settings", "open-contents"),
            MenuOutcome(False, True, "true"),
            id="opening-the-contents-closes-the-settings-menu",
        ),
        pytest.param(
            ("open-contents", "click-settings"),
            MenuOutcome(True, False, "false"),
            id="opening-the-settings-menu-closes-the-contents",
        ),
        pytest.param(
            ("click-settings", "escape"),
            MenuOutcome(False, False, None),
            id="escape-closes-the-settings-menu",
        ),
        pytest.param(
            ("open-contents", "escape"), MenuOutcome(False, False, "false"), id="escape-closes-the-contents"
        ),
    ],
)
def test_the_settings_menu_and_the_contents_panel_never_stay_open_together(
    steps: tuple[str, ...], expected: MenuOutcome
) -> None:
    html = render_html(parse_report(make_report()))

    assert run_menu_steps([script_containing(html, "data-set")], steps) == expected


def test_a_page_without_a_contents_panel_still_opens_and_closes_its_settings_menu() -> None:
    html = render_html(parse_report(make_report()))
    controls = [script_containing(html, "data-set")]

    assert (
        run_menu_steps(controls, ("click-settings",), contents=False),
        run_menu_steps(controls, ("click-settings", "escape"), contents=False),
    ) == (MenuOutcome(True, False, None), MenuOutcome(False, False, None))


def test_a_browser_without_popovers_still_opens_and_closes_the_settings_menu() -> None:
    html = render_html(parse_report(make_report()))
    controls = [script_containing(html, "data-set")]

    assert (
        run_menu_steps(controls, ("click-settings",), popover_supported=False),
        run_menu_steps(controls, ("click-settings", "escape"), popover_supported=False),
    ) == (MenuOutcome(True, False, None), MenuOutcome(False, False, None))


def test_the_display_controls_still_apply_a_choice_when_storage_throws() -> None:
    outcome = run_page_scripts(
        _boot_and_controls(_page_html()), PageRun(storage_throws=True, clicks=(("width", "full"),))
    )

    assert outcome == PageOutcome({"data-width": "full"}, {})


@pytest.mark.parametrize(
    "body",
    [
        pytest.param('{"a":1,"b":[1,2]}', id="compact-object"),
        pytest.param('[{"a":1},{"b":"two"}]', id="compact-array"),
        pytest.param('{\n  "a": 1,\n"b":   2\n}', id="object-laid-out-across-lines"),
        pytest.param('{"a":1}\n', id="compact-object-with-a-trailing-newline"),
        pytest.param("42", id="bare-number"),
        pytest.param('"text"', id="bare-string"),
        pytest.param("null", id="bare-null"),
        pytest.param("plain text", id="not-json"),
        pytest.param("", id="empty"),
    ],
)
def test_the_live_response_pane_lays_out_a_body_as_the_recorded_pane_does(body: str) -> None:
    html = render_html(parse_report(make_report(blocks=[make_request()])))
    script = script_containing(html, "function prettyBody")

    assert call_script_function(script, "prettyBody", body) == compute.read_recorded_body(body).text
