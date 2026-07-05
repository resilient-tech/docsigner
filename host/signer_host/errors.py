"""Protocol error type shared by all host modules."""


class HostError(Exception):
    """An error with a stable protocol code (CONTRACTS.md section 2)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message
