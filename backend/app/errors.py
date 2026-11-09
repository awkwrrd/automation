class WMSError(Exception):
    """Business-rule violation; rendered as an HTTP error with a readable message."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NotFound(WMSError):
    def __init__(self, what: str):
        super().__init__(f"{what} not found", 404)
