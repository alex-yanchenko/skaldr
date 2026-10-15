from skaldr.errors import ExportInvariantError
from skaldr.export.tree import Diagram, Graph, Node


def chart_as_its_data_table(node: Diagram, target_subject: str) -> tuple[Node, ...]:
    if isinstance(node.figure, Graph):
        raise ExportInvariantError(
            f"{target_subject} has no form for a {node.figure.kind} diagram; "
            "the export check should have refused it"
        )
    return node.supplement
