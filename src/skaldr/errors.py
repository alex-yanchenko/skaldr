from skaldr.export_targets import ExportTarget


class ReportError(Exception):
    """A report failed validation or reconciliation — surfaced to the operator, not swallowed."""


class ExportRejectedError(ReportError):
    def __init__(self, target: ExportTarget, why: str, instead: str, where: str | None = None) -> None:
        self.target = target
        self.why = why
        self.instead = instead
        self.where = where
        located = f"{why}, {where}" if where else why
        super().__init__(f"{located}; {instead}")


class ExportInvariantError(RuntimeError):
    pass


class AuthError(Exception):
    pass


class SeveralSignInsError(AuthError):
    pass


class ConnectorError(Exception):
    pass


class PublishError(Exception):
    pass


class ItemNotFoundError(ConnectorError):
    pass


class WriteRejectedError(ConnectorError):
    pass


class CreatedButUnfinishedError(ConnectorError):
    def __init__(self, message: str, item_id: str) -> None:
        self.item_id = item_id
        super().__init__(message)


class RegionNotFoundError(LookupError):
    pass


class UnknownGuideTopicError(LookupError):
    pass


class IndexDocumentOutlineError(ReportError):
    pass


class UnknownAnchorError(LookupError):
    pass


class RegionOutsideFileError(LookupError):
    pass


class ReadOnlyFileError(PermissionError):
    pass


class TargetAlreadyExistsError(FileExistsError):
    pass


class PageFetchError(OSError):
    pass
