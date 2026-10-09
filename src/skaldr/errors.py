class ReportError(Exception):
    """A report failed validation or reconciliation — surfaced to the operator, not swallowed."""


class AdfUnsupportedError(ReportError):
    pass


class AuthError(Exception):
    pass


class ConnectorError(Exception):
    pass


class RegionNotFoundError(LookupError):
    pass


class ReadOnlyFileError(PermissionError):
    pass


class PageFetchError(OSError):
    pass
