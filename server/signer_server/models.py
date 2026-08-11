"""Request and response shapes for CONTRACTS.md section 1.

These exist so the generated OpenAPI document is worth something. Before them
the spec described eleven endpoints with two schemas between them and every
body typed `object`, so a client generated from it was barely better than raw
HTTP. That is the whole argument against hand-writing an SDK per language:
describe the contract once, let each language generate its own.

Validation stays deliberately shallow. The codes in CONTRACTS.md
(`DOCUMENT_INVALID`, `CERT_INVALID`, `SIGNATURE_INVALID`) distinguish which
part of a request was wrong, and the checks that produce them live in `app.py`
and `signer-core`. Pydantic here only pins the field names and types; anything
it does reject is mapped back to the right code by the request-validation
handler.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------- options ----


class SigningOptions(BaseModel):
    """The `options` object. Known fields are documented; the rest pass through.

    `extra="allow"` on purpose: options grow with the standards (policies, PDF/A
    handling, appearance) and a client that sends a newer field to an older
    server should get "unsupported profile", not "malformed request".
    """

    model_config = ConfigDict(extra="allow")

    profile: str | None = Field(
        default=None,
        description="PAdES/CAdES baseline profile: B-B, B-T, B-LT, B-LTA, CCA-LTV, CCA-LTA.",
        examples=["B-T"],
    )
    reason: str | None = Field(default=None, description="Signature reason.")
    location: str | None = Field(default=None, description="Signature location.")
    field_name: str | None = Field(
        default=None, description="Signature field name; generated when omitted."
    )
    tsa: str | None = Field(
        default=None,
        description="Timestamp authority by registry name; the server default when omitted.",
        examples=["digicert"],
    )
    policy: str | None = Field(
        default=None, description="Signature policy identifier to embed."
    )
    appearance: dict[str, Any] | None = Field(
        default=None,
        description="Visible signature appearance. Omit to sign invisibly, which is "
        "what keeps a PDF/A document conformant.",
    )


# -------------------------------------------------------------- requests ----


class StartSignatureRequest(BaseModel):
    document: str = Field(description="The PDF, base64.")
    certificate: str = Field(description="The signer's certificate, base64 DER.")
    options: SigningOptions | None = None


class CompleteRequest(BaseModel):
    signature: str = Field(
        description="The signature over `to_sign_hash`, base64. PKCS#1 v1.5 for RSA, "
        "a DER ECDSA-Sig-Value for EC."
    )


class StartBatchRequest(BaseModel):
    documents: list[str] = Field(description="Up to 50 PDFs, each base64.")
    certificate: str = Field(description="One certificate for the whole batch, base64 DER.")
    options: SigningOptions | None = None


class BatchCompleteItem(BaseModel):
    session_id: str
    signature: str


class BatchCompleteRequest(BaseModel):
    items: list[BatchCompleteItem]


class SignServerSideRequest(BaseModel):
    document: str = Field(description="The document, base64.")
    options: SigningOptions | None = None


class ValidateRequest(BaseModel):
    document: str = Field(description="The signed PDF to check, base64.")


# ------------------------------------------------------------- responses ----


class PdfaClaim(BaseModel):
    """What the input claimed about PDF/A conformance, when it claimed anything."""

    part: int | None = None
    conformance: str | None = None


class SessionStarted(BaseModel):
    session_id: str
    to_sign_hash: str = Field(description="The hash to sign, base64.")
    digest_algorithm: Literal["sha256", "sha384", "sha512"]
    expires_at: str = Field(description="RFC 3339, UTC.", examples=["2026-08-11T12:00:00Z"])
    pdfa: PdfaClaim | None = Field(
        default=None, description="Present only when the input claims PDF/A."
    )
    pdfa_note: str | None = Field(
        default=None,
        description="Present only when a visible appearance would break that claim.",
    )


class AuditRecord(BaseModel):
    """Machine-readable completion record, for an audit trail."""

    signer: str
    certificate_serial: str
    certificate_issuer: str
    profile: str
    digest_algorithm: str
    field_name: str
    document_sha256: str
    completed_at: str


class StoredDocument(BaseModel):
    document_id: str
    download_url: str = Field(examples=["/api/documents/abc123"])


class SignatureCompleted(StoredDocument):
    audit: AuditRecord


class ServerSideSigned(StoredDocument):
    pdfa: PdfaClaim | None = None
    pdfa_note: str | None = None


class BatchSession(BaseModel):
    session_id: str
    to_sign_hash: str


class BatchStarted(BaseModel):
    sessions: list[BatchSession]
    digest_algorithm: Literal["sha256", "sha384", "sha512"]
    expires_at: str


class BatchCompleted(BaseModel):
    documents: list[SignatureCompleted]


class ValidationResult(BaseModel):
    signatures: list[dict[str, Any]] = Field(
        description="One entry per signature: validity, intactness, trust and the signer."
    )
    pdfa: PdfaClaim | None = None


# ----------------------------------------------------------------- error ----


class ErrorBody(BaseModel):
    code: Literal[
        "DOCUMENT_INVALID",
        "CERT_INVALID",
        "SESSION_NOT_FOUND",
        "SESSION_EXPIRED",
        "SIGNATURE_INVALID",
        "PROFILE_UNSUPPORTED",
        "INTERNAL",
    ]
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# Attached to every route so the spec documents failures, not just the happy
# path. A generated client can then type its error branch too.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Bad document, certificate or signature"},
    404: {"model": ErrorResponse, "description": "No such session or document"},
    410: {"model": ErrorResponse, "description": "Session or document expired"},
    500: {"model": ErrorResponse, "description": "Server error"},
}
