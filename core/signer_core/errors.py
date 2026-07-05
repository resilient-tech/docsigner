class SignerError(Exception):
    """Error with a stable code from CONTRACTS.md.

    Codes: DOCUMENT_INVALID, CERT_INVALID, SESSION_NOT_FOUND, SESSION_EXPIRED,
    SIGNATURE_INVALID, PROFILE_UNSUPPORTED, INTERNAL.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
