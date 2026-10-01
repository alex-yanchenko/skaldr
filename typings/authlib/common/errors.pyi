class AuthlibBaseError(Exception):
    error: str | None
    description: str
