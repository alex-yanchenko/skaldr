import json
from collections.abc import Sequence

from skaldr import compute
from skaldr.export.inline import bold, italic, labelled, plain
from skaldr.export.lower.context import Lowering
from skaldr.export.tree import Callout, CodeBlock, ListEntry, ListNode, Node, Paragraph, Tab, Tabs
from skaldr.models import Request, RequestCase, RequestFlow, RequestLike, RequestVariable
from skaldr.richtext import Code, Rich


def _is_json(body: str) -> bool:
    try:
        json.loads(body)
    except ValueError:
        return False
    return True


def _response_block(case: RequestCase) -> CodeBlock:
    body = compute.recorded_body(case.response.body).rstrip("\n")
    header_lines: list[str] = []
    for name, values in case.response.headers.items():
        header_lines += [f"{name}: {value}" for value in ([values] if isinstance(values, str) else values)]
    if header_lines:
        return CodeBlock("\n".join([*header_lines, "", body]), "http")
    return CodeBlock(body, "json" if _is_json(body) else "")


def _case_nodes(core: RequestLike, case: RequestCase, lowering: Lowering) -> tuple[Node, ...]:
    nodes: list[Node] = [CodeBlock(compute.command_for(core, case), "bash")]
    if core.command_note:
        nodes.append(Paragraph(italic(lowering.rich(core.command_note)), "muted"))
    if case.response.status is not None or core.command is None:
        nodes.append(Paragraph(labelled("Response") + plain(compute.status_line(case.response))))
    else:
        nodes.append(Paragraph(bold("Output")))
    nodes.append(_response_block(case))
    if case.verdict:
        verdict = Paragraph(labelled("Verdict") + lowering.rich(case.verdict))
        nodes.append(Callout(compute.case_tone(case), (verdict,)))
    return tuple(nodes)


def _cases(core: RequestLike, lowering: Lowering) -> list[Node]:
    if len(core.cases) == 1:
        case = core.cases[0]
        return [Paragraph(italic(plain(case.label))), *_case_nodes(core, case, lowering)]
    tabs = tuple(
        Tab(plain(case.label), _case_nodes(core, case, lowering), compute.case_tone(case))
        for case in core.cases
    )
    return [Tabs(tabs)]


def _variable_entry(variable: RequestVariable) -> ListEntry:
    if variable.secret:
        detail = "a secret, supply your own"
    elif variable.example:
        detail = f"for example {variable.example}"
    else:
        detail = "supply a value"
    return ListEntry(
        (Code("{{" + variable.name + "}}"), *plain(f" {variable.label or variable.name}: {detail}"))
    )


def _variables(variables: Sequence[RequestVariable]) -> list[Node]:
    if not variables:
        return []
    return [Paragraph(bold("Values you supply")), ListNode("bullet", tuple(map(_variable_entry, variables)))]


def lower_request(block: Request, lowering: Lowering) -> list[Node]:
    return [Paragraph(bold(block.label)), *_variables(block.variables), *_cases(block, lowering)]


def lower_request_flow(block: RequestFlow, lowering: Lowering) -> list[Node]:
    nodes: list[Node] = [Paragraph(bold(block.label)), *_variables(block.variables)]
    for index, step in enumerate(block.steps, start=1):
        heading: Rich = bold(f"Step {index} of {len(block.steps)}: {step.label}")
        for position, capture in enumerate(step.captures):
            heading += (*plain(", captures " if position == 0 else ", "), Code(capture.name))
        nodes.append(Paragraph(heading))
        nodes += _cases(step, lowering)
    return nodes
