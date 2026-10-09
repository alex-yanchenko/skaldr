from collections.abc import Sequence

from skaldr import compute
from skaldr.export.inline import bold, italic, plain
from skaldr.export.lower.context import Lowering, bullets, spaced, with_bold_label
from skaldr.export.runs import ExportRich
from skaldr.export.tree import Callout, CodeBlock, ListEntry, Node, Paragraph, Tab, Tabs
from skaldr.models import (
    Request,
    RequestCapture,
    RequestCase,
    RequestFlow,
    RequestLike,
    RequestQuery,
    RequestStep,
    RequestVariable,
)
from skaldr.richtext import Code, Plain


def _response_block(case: RequestCase) -> CodeBlock:
    recorded = compute.read_recorded_body(case.response.body)
    body = recorded.text.rstrip("\n")
    header_lines = [
        f"{name}: {value}"
        for name, values in case.response.headers.items()
        for value in ([values] if isinstance(values, str) else values)
    ]
    if header_lines:
        return CodeBlock("\n".join([*header_lines, "", body]), "http")
    return CodeBlock(body, "json" if recorded.is_json else "")


def _response_caption(core: RequestLike, case: RequestCase) -> Paragraph:
    caption = compute.response_caption(core, case.response)
    status = plain(compute.status_line(case.response)) if caption.shows_status else ()
    return Paragraph(with_bold_label(caption.label, status))


def _query_nodes(core: RequestLike, case: RequestCase, query: RequestQuery) -> list[Node]:
    return [
        Paragraph(with_bold_label("Query", plain(query.runner))),
        CodeBlock(compute.query_text_for(query, core, case), query.lang),
    ]


def _command_nodes(core: RequestLike, case: RequestCase, lowering: Lowering) -> list[Node]:
    nodes: list[Node] = [CodeBlock(compute.command_for(core, case), "bash")]
    if core.command_note:
        nodes.append(Paragraph(italic(lowering.rich(core.command_note)), "muted"))
    return nodes


def _case_nodes(core: RequestLike, case: RequestCase, lowering: Lowering) -> tuple[Node, ...]:
    nodes = (
        _query_nodes(core, case, core.query)
        if core.query is not None
        else _command_nodes(core, case, lowering)
    )
    nodes += [_response_caption(core, case), _response_block(case)]
    if case.verdict:
        verdict = Paragraph(with_bold_label("Verdict", lowering.rich(case.verdict)))
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
        spaced([(Code("{{" + variable.name + "}}"),), plain(f"{variable.label or variable.name}: {detail}")])
    )


def _variables(variables: Sequence[RequestVariable]) -> list[Node]:
    if not variables:
        return []
    return [Paragraph(bold("Values you supply")), bullets(map(_variable_entry, variables))]


def _capture_origin(capture: RequestCapture) -> ExportRich:
    if capture.json_path is not None:
        return (Code(capture.name), Plain(" from "), Code(capture.json_path))
    return (Code(capture.name), Plain(" from the whole response body"))


def _step_title(step: RequestStep, index: int, count: int) -> ExportRich:
    title = bold(f"Step {index} of {count}: {step.label}")
    captures = spaced([_capture_origin(capture) for capture in step.captures], ", ")
    return (*title, Plain(", captures "), *captures) if captures else title


def lower_request(block: Request, lowering: Lowering) -> list[Node]:
    return [Paragraph(bold(block.label)), *_variables(block.variables), *_cases(block, lowering)]


def lower_request_flow(block: RequestFlow, lowering: Lowering) -> list[Node]:
    nodes: list[Node] = [Paragraph(bold(block.label)), *_variables(block.variables)]
    for index, step in enumerate(block.steps, start=1):
        nodes.append(Paragraph(_step_title(step, index, len(block.steps))))
        nodes += _cases(step, lowering)
    return nodes
