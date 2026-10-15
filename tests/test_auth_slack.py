import json

import httpx2
import pytest

from skaldr.auth import cli as auth_cli
from skaldr.auth.slack import verify_slack_token
from skaldr.auth.store import (
    SignIn,
    SlackCredentials,
    find_slack,
    load_slack,
    require_slack_for_a_target,
    save_jira,
    save_slack,
    stored_slack_sign_ins,
)
from skaldr.errors import AuthError
from tests.factories.auth_factory import (
    SLACK_USER_TOKEN,
    InMemoryKeyring,
    assert_secret_not_in_error_chain,
    fake_api,
    make_jira_credentials,
    make_slack_credentials,
    refusing_connections,
    slack_auth_answer,
)

AUTH_TEST = "/api/auth.test"
OTHER_GARDEN = make_slack_credentials(
    access_token="xoxp-1111-other-token", team_id="T0EXAMPLE2", team_name="Other Garden"
)
NOT_A_USER_TOKEN = (
    "skaldr signs in to Slack with a user token, which starts with xoxp-; copy the User OAuth Token from "
    "your Slack app's OAuth & Permissions page"
)
TOKEN_REJECTED = (
    "Slack rejected the user token ({code}). Copy the User OAuth Token again from your app at "
    "https://api.slack.com/apps, under OAuth & Permissions"
)
SIGN_IN_GUIDE = (
    "Create a Slack app once at https://api.slack.com/apps, give it the user token scopes canvases:read, "
    "canvases:write, chat:write, install it to your workspace, and copy its User OAuth Token\n"
)


def _stored_slack() -> list[object]:
    return [entry.credentials for entry in stored_slack_sign_ins()]


def test_a_user_token_is_checked_with_auth_test_and_named_by_its_workspace() -> None:
    seen: list[httpx2.Request] = []

    credentials = verify_slack_token(
        SLACK_USER_TOKEN, transport=fake_api({AUTH_TEST: (200, slack_auth_answer())}, seen)
    )

    assert (
        credentials,
        [(request.method, str(request.url), request.headers["authorization"]) for request in seen],
    ) == (
        make_slack_credentials(),
        [("POST", "https://slack.com/api/auth.test", f"Bearer {SLACK_USER_TOKEN}")],
    )


@pytest.mark.parametrize(
    "token", ["xoxb-0000-bot-token", "", "  xoxp-0000"], ids=["bot", "empty", "leading-space"]
)
def test_a_token_that_is_not_a_user_token_is_refused_before_slack_is_asked(token: str) -> None:
    seen: list[httpx2.Request] = []

    with pytest.raises(AuthError) as raised:
        verify_slack_token(token, transport=fake_api({}, seen))

    assert (str(raised.value), seen) == (NOT_A_USER_TOKEN, [])


@pytest.mark.parametrize("code", ["invalid_auth", "token_revoked", "account_inactive"])
def test_a_rejected_token_is_refused_naming_slacks_error(code: str) -> None:
    with pytest.raises(AuthError) as raised:
        verify_slack_token(
            SLACK_USER_TOKEN, transport=fake_api({AUTH_TEST: (200, {"ok": False, "error": code})}, [])
        )

    assert str(raised.value) == TOKEN_REJECTED.format(code=code)
    assert_secret_not_in_error_chain(raised.value, SLACK_USER_TOKEN)


def test_another_refusal_is_named_by_its_code() -> None:
    with pytest.raises(AuthError, match=r"^Slack refused auth\.test \(team_access_not_granted\)$"):
        verify_slack_token(
            SLACK_USER_TOKEN,
            transport=fake_api({AUTH_TEST: (200, {"ok": False, "error": "team_access_not_granted"})}, []),
        )


def test_an_unexpected_status_is_named() -> None:
    with pytest.raises(AuthError, match=r"^Slack answered HTTP 503 for auth\.test$"):
        verify_slack_token(SLACK_USER_TOKEN, transport=fake_api({AUTH_TEST: (503, {})}, []))


@pytest.mark.parametrize(
    "body", [b"<html>secret-answer</html>", {"team": "secret-answer"}], ids=["html", "no-ok"]
)
def test_an_answer_that_is_not_a_sign_in_record_is_refused_without_its_content(body: object) -> None:
    with pytest.raises(AuthError) as raised:
        verify_slack_token(SLACK_USER_TOKEN, transport=fake_api({AUTH_TEST: (200, body)}, []))

    assert str(raised.value) == "Slack's auth.test answer is not a sign-in record"
    assert_secret_not_in_error_chain(raised.value, "secret-answer")


def test_an_unreachable_slack_is_named() -> None:
    with pytest.raises(AuthError, match=r"^Could not reach Slack: connection refused$"):
        verify_slack_token(SLACK_USER_TOKEN, transport=refusing_connections())


def test_a_saved_sign_in_loads_back_and_is_listed_in_the_index(keychain: InMemoryKeyring) -> None:
    save_slack(make_slack_credentials())

    assert (load_slack(), json.loads(keychain.entries[("skaldr", "index")])) == (
        SignIn(make_slack_credentials(), "keychain"),
        {"jira": [], "notion": [], "slack": ["slack:T0EXAMPLE1"]},
    )


def test_a_jira_sign_in_writes_no_slack_list_into_the_index(keychain: InMemoryKeyring) -> None:
    save_jira(make_jira_credentials())

    assert json.loads(keychain.entries[("skaldr", "index")]) == {
        "jira": ["jira:https://example.atlassian.net"],
        "notion": [],
    }


def test_a_sign_in_without_a_workspace_id_is_not_saved(keychain: InMemoryKeyring) -> None:
    with pytest.raises(AuthError, match=r"^A Slack sign-in without a workspace id cannot be saved$"):
        save_slack(make_slack_credentials(team_id=None))

    assert keychain.entries == {}


def test_a_second_workspace_is_kept_beside_the_first_and_each_is_found_by_its_id_or_name() -> None:
    save_slack(make_slack_credentials())
    save_slack(OTHER_GARDEN)

    found = [find_slack(selector) for selector in ("T0EXAMPLE2", "Example Garden", "Nowhere")]

    assert ([None if entry is None else entry.credentials for entry in found], _stored_slack()) == (
        [OTHER_GARDEN, make_slack_credentials(), None],
        [make_slack_credentials(), OTHER_GARDEN],
    )


def test_a_target_naming_no_workspace_among_several_is_asked_to_name_one() -> None:
    save_slack(make_slack_credentials())
    save_slack(OTHER_GARDEN)

    with pytest.raises(AuthError) as raised:
        require_slack_for_a_target(None)

    assert str(raised.value) == (
        "Signed in to several Slack workspaces (Example Garden (T0EXAMPLE1), Other Garden (T0EXAMPLE2)); "
        "name one with `workspace` in the target's `where`"
    )


def test_a_target_naming_a_workspace_nobody_signed_in_to_lists_the_signed_in_ones() -> None:
    save_slack(make_slack_credentials())

    with pytest.raises(AuthError) as raised:
        require_slack_for_a_target("Nowhere")

    assert str(raised.value) == (
        "No Slack sign-in matches workspace `Nowhere`; signed in to Example Garden (T0EXAMPLE1)"
    )


@pytest.mark.parametrize(
    ("workspace", "message"),
    [
        pytest.param(None, "Not signed in to Slack; run `skaldr auth slack`", id="no-workspace"),
        pytest.param(
            "Example Garden",
            "Not signed in to Slack workspace Example Garden; run `skaldr auth slack`",
            id="named",
        ),
    ],
)
def test_a_target_with_no_sign_in_points_at_skaldr_auth_slack(workspace: str | None, message: str) -> None:
    with pytest.raises(AuthError) as raised:
        require_slack_for_a_target(workspace)

    assert str(raised.value) == message


def test_the_environment_token_wins_when_no_workspace_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    save_slack(make_slack_credentials())
    monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-2222-ci-token")

    assert (load_slack(), load_slack("T0EXAMPLE1")) == (
        SignIn(SlackCredentials(access_token="xoxp-2222-ci-token"), "environment"),
        SignIn(make_slack_credentials(), "keychain"),
    )


def test_an_environment_token_that_is_not_a_user_token_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_USER_TOKEN", "xoxb-bot")

    with pytest.raises(AuthError) as raised:
        load_slack()

    assert str(raised.value) == f"SLACK_USER_TOKEN: {NOT_A_USER_TOKEN}"


def _answer_the_token_prompt(monkeypatch: pytest.MonkeyPatch, token: str) -> None:
    def hidden(_prompt: str) -> str:
        return token

    monkeypatch.setattr(auth_cli, "getpass", hidden)


def test_auth_slack_verifies_the_token_and_saves_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _answer_the_token_prompt(monkeypatch, f"  {SLACK_USER_TOKEN}\n")

    exit_code = auth_cli.main(["slack"], transport=fake_api({AUTH_TEST: (200, slack_auth_answer())}, []))

    captured = capsys.readouterr()
    assert (exit_code, captured.out, captured.err, _stored_slack()) == (
        0,
        SIGN_IN_GUIDE + "Signed in to Slack workspace Example Garden as rowan. Saved to the keychain.\n",
        "",
        [make_slack_credentials()],
    )


def test_auth_slack_saves_nothing_when_slack_rejects_the_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _answer_the_token_prompt(monkeypatch, SLACK_USER_TOKEN)

    exit_code = auth_cli.main(
        ["slack"], transport=fake_api({AUTH_TEST: (200, {"ok": False, "error": "invalid_auth"})}, [])
    )

    captured = capsys.readouterr()
    assert (exit_code, captured.err, _stored_slack()) == (
        1,
        f"error: {TOKEN_REJECTED.format(code='invalid_auth')}\n",
        [],
    )


def test_auth_slack_refuses_an_empty_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _answer_the_token_prompt(monkeypatch, "   ")

    exit_code = auth_cli.main(["slack"], transport=fake_api({}, []))

    assert (exit_code, capsys.readouterr().err) == (1, "error: A Slack user token is required\n")


def test_status_lists_each_slack_sign_in_and_the_environment_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    save_slack(make_slack_credentials())
    monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-2222-ci-token")

    exit_code = auth_cli.main(["status"])

    slack_lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("slack")]
    assert (exit_code, slack_lines) == (
        0,
        [
            "slack   user token from SLACK_USER_TOKEN (environment)",
            "slack   signed in to workspace Example Garden (id T0EXAMPLE1) as rowan (keychain)",
        ],
    )


def test_status_says_how_to_sign_in_to_slack(capsys: pytest.CaptureFixture[str]) -> None:
    auth_cli.main(["status"])

    assert "slack   not signed in (run `skaldr auth slack`)" in capsys.readouterr().out.splitlines()


def test_logout_slack_forgets_the_token_and_points_at_revoking_it(capsys: pytest.CaptureFixture[str]) -> None:
    save_slack(make_slack_credentials())
    save_slack(OTHER_GARDEN)

    exit_code = auth_cli.main(["logout", "slack", "Other Garden"])

    assert (exit_code, capsys.readouterr().out, _stored_slack()) == (
        0,
        "Signed out of Slack: removed from the keychain. Revoke the token itself in your Slack app at "
        "https://api.slack.com/apps, under OAuth & Permissions\n",
        [make_slack_credentials()],
    )


def test_logout_slack_for_a_workspace_nobody_signed_in_to_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    assert (auth_cli.main(["logout", "slack", "Nowhere"]), capsys.readouterr().out) == (
        0,
        "Not signed in to Slack workspace Nowhere.\n",
    )
