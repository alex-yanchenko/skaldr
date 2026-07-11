class ReportError(Exception):
    """A report failed validation or reconciliation — surfaced to the operator, not swallowed."""
