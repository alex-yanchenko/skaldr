from typing import Literal

from typing_extensions import NotRequired, TypedDict

from skaldr.export.tree import HeadingLevel

LozengeColor = Literal["neutral", "purple", "blue", "red", "yellow", "green"]
PanelType = Literal["info", "note", "success", "warning", "error"]
TaskState = Literal["TODO", "DONE"]
SubsupKind = Literal["sub", "sup"]


class AdfStrong(TypedDict):
    type: Literal["strong"]


class AdfEm(TypedDict):
    type: Literal["em"]


class AdfUnderline(TypedDict):
    type: Literal["underline"]


class AdfStrike(TypedDict):
    type: Literal["strike"]


class AdfCode(TypedDict):
    type: Literal["code"]


class AdfLinkAttrs(TypedDict):
    href: str


class AdfLink(TypedDict):
    type: Literal["link"]
    attrs: AdfLinkAttrs


class AdfTextColorAttrs(TypedDict):
    color: str


class AdfTextColor(TypedDict):
    type: Literal["textColor"]
    attrs: AdfTextColorAttrs


class AdfSubsupAttrs(TypedDict):
    type: SubsupKind


class AdfSubsup(TypedDict):
    type: Literal["subsup"]
    attrs: AdfSubsupAttrs


AdfMark = AdfStrong | AdfEm | AdfUnderline | AdfStrike | AdfCode | AdfLink | AdfTextColor | AdfSubsup


class AdfText(TypedDict):
    type: Literal["text"]
    text: str
    marks: NotRequired[list[AdfMark]]


class AdfStatusAttrs(TypedDict):
    text: str
    color: LozengeColor


class AdfStatus(TypedDict):
    type: Literal["status"]
    attrs: AdfStatusAttrs


class AdfInlineCardAttrs(TypedDict):
    url: str


class AdfInlineCard(TypedDict):
    type: Literal["inlineCard"]
    attrs: AdfInlineCardAttrs


class AdfHardBreak(TypedDict):
    type: Literal["hardBreak"]


AdfInline = AdfText | AdfStatus | AdfInlineCard | AdfHardBreak


class AdfParagraph(TypedDict):
    type: Literal["paragraph"]
    content: NotRequired[list[AdfInline]]


class AdfHeadingAttrs(TypedDict):
    level: HeadingLevel


class AdfHeading(TypedDict):
    type: Literal["heading"]
    attrs: AdfHeadingAttrs
    content: NotRequired[list[AdfInline]]


class AdfListItem(TypedDict):
    type: Literal["listItem"]
    content: "list[AdfBlock]"


class AdfBulletList(TypedDict):
    type: Literal["bulletList"]
    content: list[AdfListItem]


class AdfOrderedListAttrs(TypedDict):
    order: int


class AdfOrderedList(TypedDict):
    type: Literal["orderedList"]
    attrs: NotRequired[AdfOrderedListAttrs]
    content: list[AdfListItem]


class AdfTaskItemAttrs(TypedDict):
    localId: str
    state: TaskState


class AdfTaskItem(TypedDict):
    type: Literal["taskItem"]
    attrs: AdfTaskItemAttrs
    content: NotRequired[list[AdfInline]]


class AdfTaskListAttrs(TypedDict):
    localId: str


class AdfTaskList(TypedDict):
    type: Literal["taskList"]
    attrs: AdfTaskListAttrs
    content: "list[AdfTaskItem | AdfTaskList]"


class AdfCodeBlockAttrs(TypedDict):
    language: str


class AdfCodeBlock(TypedDict):
    type: Literal["codeBlock"]
    attrs: NotRequired[AdfCodeBlockAttrs]
    content: NotRequired[list[AdfText]]


class AdfBlockquote(TypedDict):
    type: Literal["blockquote"]
    content: list[AdfParagraph]


class AdfRule(TypedDict):
    type: Literal["rule"]


class AdfPanelAttrs(TypedDict):
    panelType: PanelType


class AdfPanel(TypedDict):
    type: Literal["panel"]
    attrs: AdfPanelAttrs
    content: "list[AdfBlock]"


class AdfCellAttrs(TypedDict):
    background: str


class AdfTableCell(TypedDict):
    type: Literal["tableCell"]
    attrs: NotRequired[AdfCellAttrs]
    content: list[AdfParagraph]


class AdfTableHeader(TypedDict):
    type: Literal["tableHeader"]
    attrs: NotRequired[AdfCellAttrs]
    content: list[AdfParagraph]


class AdfTableRow(TypedDict):
    type: Literal["tableRow"]
    content: list[AdfTableCell | AdfTableHeader]


class AdfTableAttrs(TypedDict):
    isNumberColumnEnabled: bool
    layout: Literal["default"]


class AdfTable(TypedDict):
    type: Literal["table"]
    attrs: AdfTableAttrs
    content: list[AdfTableRow]


class AdfExpandAttrs(TypedDict):
    title: str


class AdfExpand(TypedDict):
    type: Literal["expand"]
    attrs: AdfExpandAttrs
    content: "list[AdfBlock]"


class AdfNestedExpand(TypedDict):
    type: Literal["nestedExpand"]
    attrs: AdfExpandAttrs
    content: "list[AdfBlock]"


AdfBlock = (
    AdfParagraph
    | AdfHeading
    | AdfBulletList
    | AdfOrderedList
    | AdfTaskList
    | AdfCodeBlock
    | AdfBlockquote
    | AdfRule
    | AdfPanel
    | AdfTable
    | AdfExpand
    | AdfNestedExpand
)


class AdfDoc(TypedDict):
    version: Literal[1]
    type: Literal["doc"]
    content: list[AdfBlock]
