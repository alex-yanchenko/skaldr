import re
import sys
from typing import Final

from skaldr.errors import ConnectorError, ItemNotFoundError
from skaldr.publish.notion.api import NotionApi

CODE_OR_PERSON_MENTION: Final = re.compile(
    r"(?P<code>(?P<fence>```|~~~).*?(?P=fence)|``.*?``|`[^`\n]*`)"
    r'|<mention-user url="user://(?P<id>[0-9A-Fa-f-]+)">(?P<label>.*?)</mention-user>',
    re.DOTALL,
)


class KnownPeople:
    def __init__(self, api: NotionApi) -> None:
        self._api = api
        self._notion_knows: dict[str, bool] = {}
        self._connection_reads_users: bool | None = None

    def as_written(self, text: str) -> str:
        return CODE_OR_PERSON_MENTION.sub(self._mention_or_label, text)

    def _mention_or_label(self, found: re.Match[str]) -> str:
        user_id = found.group("id")
        if user_id is None or self._connection_reads_users is False:
            return found.group(0)
        label = found.group("label")
        knows = self._notion_knows.get(user_id)
        if knows is None:
            knows = self._answers_for(user_id)
            if knows is False:
                print(
                    f"warning: Notion has no user with id {user_id}, "
                    f"so the page shows {label} as text instead of a mention",
                    file=sys.stderr,
                )
        return label if knows is False else found.group(0)

    def _answers_for(self, user_id: str) -> bool | None:
        try:
            self._api.user(user_id)
        except ItemNotFoundError:
            return self._no_such_user_if_the_connection_can_tell(user_id)
        except ConnectorError:
            return None
        self._notion_knows[user_id] = True
        return True

    def _no_such_user_if_the_connection_can_tell(self, user_id: str) -> bool | None:
        if not self._connection_can_read_users():
            return None
        self._notion_knows[user_id] = False
        return False

    def _connection_can_read_users(self) -> bool:
        if self._connection_reads_users is None:
            try:
                self._api.first_user()
            except ConnectorError:
                self._connection_reads_users = False
                print(
                    "warning: skaldr could not check the people on this page because the Notion connection "
                    "cannot read user information, so mentions are written as they are",
                    file=sys.stderr,
                )
            else:
                self._connection_reads_users = True
        return self._connection_reads_users
