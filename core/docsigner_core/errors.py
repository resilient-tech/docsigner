class SignerError(Exception):
    """A failure with a code callers can switch on. The list is in CONTRACTS.md."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
