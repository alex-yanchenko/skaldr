from skaldr.export.runs import Chip
from skaldr.export.tree import ListEntry, ListNode, TableCell, Toggle
from skaldr.richtext import Plain

API_LEGEND = Toggle(
    (Plain("Legend: badges used on this page"),),
    None,
    (ListNode("bullet", (ListEntry((Chip("api", "blue"), Plain(" "), Plain("the API"))),)),),
)


def cell_texts_of(*texts: str) -> tuple[TableCell, ...]:
    return tuple(TableCell((Plain(text),) if text else ()) for text in texts)
