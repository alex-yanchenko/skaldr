class ReportError(Exception):
    """A report failed validation or reconciliation — surfaced to the operator, not swallowed."""


class AuthError(Exception):
    pass


class ReadOnlyFileError(PermissionError):
    pass


class PageFetchError(OSError):
    pass
