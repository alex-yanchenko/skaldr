from dataclasses import dataclass
from typing import Final

from skaldr.errors import WriteRejectedError
from skaldr.publish.notion.api import NotionApi
from skaldr.publish.notion.responses import DataSource

DATABASE_BLOCK: Final = "child_database"
PAGE_BLOCK: Final = "child_page"


@dataclass(frozen=True)
class ParentLookup:
    data_source: DataSource | None

    @property
    def is_a_page(self) -> bool:
        return self.data_source is None


def look_up_parent(api: NotionApi, parent_id: str) -> ParentLookup:
    block = api.block(parent_id)
    if block.in_trash:
        raise WriteRejectedError(
            f"Notion page {parent_id} is in the trash, so skaldr cannot create a page under it"
        )
    if block.type == PAGE_BLOCK:
        return ParentLookup(None)
    if block.type != DATABASE_BLOCK:
        raise WriteRejectedError(
            f"Notion block {parent_id} is a {block.type}, not a page or a database, so skaldr cannot "
            "create a page under it"
        )
    sources = api.database(parent_id).data_sources
    if len(sources) != 1:
        raise WriteRejectedError(
            f"Notion database {parent_id} has {len(sources)} data sources; skaldr adds rows only to a "
            "database with one"
        )
    return ParentLookup(api.data_source(sources[0].id))
