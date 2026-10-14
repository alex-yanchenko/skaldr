from skaldr.export_targets import ExportTarget


class ReportError(Exception):
    """A report failed validation or reconciliation — surfaced to the operator, not swallowed."""


class AdfUnsupportedError(ReportError):
    pass


class ExportRejectedError(ReportError):
    def __init__(self, target: ExportTarget, why: str, instead: str, where: str | None = None) -> None:
        self.target = target
        self.why = why
        self.instead = instead
        self.where = where
        located = f"{why}, {where}" if where else why
        super().__init__(f"{located}; {instead}")


class AuthError(Exception):
    pass


class ConnectorError(Exception):
    pass


class PublishError(Exception):
    pass


class ItemNotFoundError(ConnectorError):
    pass


class WriteRejectedError(ConnectorError):
    pass


class RegionNotFoundError(LookupError):
    pass


class UnknownGuideTopicError(LookupError):
    pass


class ReadOnlyFileError(PermissionError):
    pass


class PageFetchError(OSError):
    pass
