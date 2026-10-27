"""Exceptions whose message is safe to show to the shop owner."""


class UserError(Exception):
    """A problem the owner can understand and fix. The message is shown as-is."""

    def __init__(self, message: str, title: str = "Please check"):
        super().__init__(message)
        self.message = message
        self.title = title


class ValidationError(UserError):
    pass


class StockError(UserError):
    def __init__(self, message: str):
        super().__init__(message, "Not enough stock")


class NotFoundError(UserError):
    def __init__(self, message: str):
        super().__init__(message, "Not found")


class PrinterError(UserError):
    def __init__(self, message: str):
        super().__init__(message, "Printer problem")
