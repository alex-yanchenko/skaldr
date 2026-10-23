import re
import sys
from typing import Final

from skaldr.errors import ConnectorError, ItemNotFoundError
from skaldr.publish.notion.api import NotionApi

PERSON_MENTION: Final = re.compile(r'<mention-user url="user://([0-9A-Fa-f-]+)">(.*?)</mention-user>')


class KnownPeople:
    def __init__(self, api: NotionApi) -> None:
        self._api = api
        self._notion_knows: dict[str, bool] = {}

    def as_written(self, text: str) -> str:
        return PERSON_MENTION.sub(self._mention_or_label, text)

    def _mention_or_label(self, found: re.Match[str]) -> str:
        user_id, label = found.group(1), found.group(2)
        if user_id not in self._notion_knows:
            self._notion_knows[user_id] = self._answers_for(user_id)
            if not self._notion_knows[user_id]:
                print(
                    f"warning: Notion has no user user://{user_id}, "
                    f"so the page shows {label} as text instead of a mention",
                    file=sys.stderr,
                )
        return found.group(0) if self._notion_knows[user_id] else label

    def _answers_for(self, user_id: str) -> bool:
        try:
            self._api.user(user_id)
        except ItemNotFoundError:
            return False
        except ConnectorError:
            return True
        return True
