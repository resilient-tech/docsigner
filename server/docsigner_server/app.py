"""The routes. Thin on purpose: this file only speaks HTTP, core does the work."""

import base64
import hashlib
from datetime import datetime, timedelta, timezone

from cryptography import x509 as pyca_x509

from fastapi import Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from docsigner_core import SessionState, SignerError, SigningSession, sign_with_p12, validate
from docsigner_core.cades import CadesSession, CadesState, sign_cades_with_p12
from docsigner_core.pdfa import detect_pdfa
from docsigner_core.trust import build_validation_context, make_timestamper, resolve_tsa_url
from docsigner_core.xades import sign_xml_with_p12

from .config import Config
from .models import (
    ERROR_RESPONSES,
    BatchCompleted,
    BatchCompleteRequest,
    BatchStarted,
    CompleteRequest,
    SessionStarted,
    ServerSideSigned,
    SignatureCompleted,
    SignServerSideRequest,
    StartBatchRequest,
    StartSignatureRequest,
    StoredDocument,
    ValidateRequest,
    ValidationResult,
)
from .store import Expired, FileStore, Missing

config = Config.from_env()

app = FastAPI(
    title="docsigner-server",
    version="1.0.0",
    summary="Sign PDFs, any file (CAdES) and XML (XAdES) with a token or a server-held key.",
    description=(
        "The document never leaves this server. A browser carries a 32-byte hash "
        "out and a signature back, so a 200 MB file signs as fast as a 200 KB one.\n\n"
        "The protocol is frozen in CONTRACTS.md section 1. Generate a client from "
        "this document rather than hand-writing one."
    ),
)
# The demo page runs on another port.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

sessions = FileStore(config.session_dir, config.session_ttl_seconds)
documents = FileStore(config.document_dir, config.document_ttl_seconds)

_HTTP_STATUS = {
    "DOCUMENT_INVALID": 400,
    "CERT_INVALID": 400,
    "SESSION_NOT_FOUND": 404,
    "SESSION_EXPIRED": 410,
    "SIGNATURE_INVALID": 400,
    "PROFILE_UNSUPPORTED": 400,
    "INTERNAL": 500,
}


@app.exception_handler(SignerError)
async def signer_error_handler(request: Request, exc: SignerError):
    return JSONResponse(
        status_code=_HTTP_STATUS.get(exc.code, 500),
        content={"error": {"code": exc.code, "message": exc.message}},
    )


# Which field was wrong picks the error code, so a bad certificate and a bad
# signature stay two different answers instead of one vague one.
_FIELD_ERROR_CODES = {
    "certificate": "CERT_INVALID",
    "signature": "SIGNATURE_INVALID",
}


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    code = "DOCUMENT_INVALID"
    for error in exc.errors():
        for part in error.get("loc", ()):
            if part in _FIELD_ERROR_CODES:
                code = _FIELD_ERROR_CODES[part]
                break
        else:
            continue
        break
    return JSONResponse(
        status_code=400,
        content={"error": {"code": code, "message": "malformed request body"}},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    # This runs outside the CORS layer, so set the header by hand. Without it
    # the browser calls a 500 a network failure and the user sees nothing useful.
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL", "message": "internal server error"}},
        headers={"Access-Control-Allow-Origin": "*"},
    )


def _iso_z(dt: datetime) -> str:
    """Timestamp ending in Z. The built-in writes +00:00, which we do not want."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _expires_at() -> str:
    return _iso_z(datetime.now(timezone.utc) + timedelta(seconds=config.session_ttl_seconds))


def _b64_bytes(value, field: str, error_code: str) -> bytes:
    """Decode a base64 field, blaming the right field if it is junk."""
    if not isinstance(value, str) or not value:
        raise SignerError(error_code, f"'{field}' must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except Exception:
        raise SignerError(error_code, f"'{field}' is not valid base64") from None


def _document_bytes(value) -> bytes:
    pdf_bytes = _b64_bytes(value, "document", "DOCUMENT_INVALID")
    if len(pdf_bytes) > config.max_pdf_bytes:
        raise SignerError(
            "DOCUMENT_INVALID", f"document exceeds the {config.max_pdf_mb} MB limit"
        )
    return pdf_bytes


def _options_dict(options) -> dict:
    """Options model to the plain dict core wants. Unset fields stay absent."""
    return options.model_dump(exclude_none=True) if options else {}


def _signing_validation_context():
    if config.trust_dir:
        # "require" so the whole chain gets covered. A gap means Adobe will not
        # show the LTV badge.
        return build_validation_context(
            config.trust_dir, allow_fetching=True, revocation_mode="require"
        )
    return None


def _stored_document_response(signed_pdf: bytes) -> dict:
    document_id = documents.put(signed_pdf)
    return {"document_id": document_id, "download_url": f"/api/documents/{document_id}"}


def _timestamper(tsa_url: str | None):
    """The clock for this call.

    Credentials go out only to the clock they were issued for. A request may
    name any public clock, and those must never see the paid account's login.
    """
    own = bool(tsa_url) and tsa_url == config.tsa_url
    return make_timestamper(
        tsa_url,
        auth=config.tsa_auth if own else None,
        bearer=config.tsa_bearer if own else None,
    )


def _request_timestamper(options: dict):
    """The clock the caller named, or the configured one."""
    return _timestamper(resolve_tsa_url(options.get("tsa"), config.tsa_url))


def _pdfa_fields(pdf_bytes: bytes, options: dict) -> dict:
    """Extra reply fields when the file claims to be PDF/A."""
    pdfa = detect_pdfa(pdf_bytes)
    if not pdfa:
        return {}
    fields = {"pdfa": pdfa}
    if options.get("appearance"):
        fields["pdfa_note"] = (
            f"PDF/A-{pdfa['part']}{pdfa['conformance'] or ''} detected: the visible"
            " stamp uses an unembedded font, which breaks PDF/A conformance."
            " Omit 'appearance' to sign invisibly and preserve it."
        )
    return fields


@app.post(
    "/api/signatures",
    response_model=SessionStarted,
    response_model_exclude_none=True,
    responses=ERROR_RESPONSES,
    summary="Start a token signing session",
    tags=["PDF"],
)
def start_signature(payload: StartSignatureRequest = Body(...)):
    pdf_bytes = _document_bytes(payload.document)
    cert_der = _b64_bytes(payload.certificate, "certificate", "CERT_INVALID")
    options = _options_dict(payload.options)

    state, to_sign_hash, digest_algorithm = SigningSession.start(
        pdf_bytes,
        cert_der,
        options,
        timestamper=_request_timestamper(options),
        validation_context=_signing_validation_context(),
        strict_ltv=config.strict_ltv,
        policy_dir=config.policy_dir,
    )
    session_id = sessions.put(state.to_bytes())
    return {
        "session_id": session_id,
        "to_sign_hash": base64.b64encode(to_sign_hash).decode("ascii"),
        "digest_algorithm": digest_algorithm,
        "expires_at": _expires_at(),
        **_pdfa_fields(pdf_bytes, options),
    }


def _load_session(session_id: str) -> bytes:
    try:
        return sessions.get(session_id)
    except Expired:
        raise SignerError("SESSION_EXPIRED", "session has expired") from None
    except Missing:
        raise SignerError("SESSION_NOT_FOUND", "no such session") from None


def _audit_record(state: SessionState, signed_pdf: bytes) -> dict:
    """What got signed, by whom, when. For the caller's audit trail."""
    cert = pyca_x509.load_der_x509_certificate(state.cert_der)
    return {
        "signer": cert.subject.rfc4514_string(),
        "certificate_serial": str(cert.serial_number),
        "certificate_issuer": cert.issuer.rfc4514_string(),
        "profile": state.profile,
        "digest_algorithm": state.digest_algorithm,
        "field_name": state.field_name,
        "document_sha256": hashlib.sha256(signed_pdf).hexdigest(),
        "completed_at": _iso_z(datetime.now(timezone.utc)),
    }


def _complete_one(session_id: str, signature: bytes) -> dict:
    try:
        state = SessionState.from_bytes(_load_session(session_id))
    except SignerError:
        raise
    except Exception:
        # Wrong kind of session, or a corrupt blob. Either way, not ours.
        raise SignerError("SESSION_NOT_FOUND", "no such session") from None

    signed_pdf = SigningSession.complete(
        state,
        signature,
        timestamper=_timestamper(state.tsa_url or config.tsa_url),
        validation_context=_signing_validation_context(),
        strict_ltv=config.strict_ltv,
    )
    # One use only. A failed try can be retried; a good one is spent.
    sessions.delete(session_id)
    return {**_stored_document_response(signed_pdf), "audit": _audit_record(state, signed_pdf)}


@app.post(
    "/api/signatures/{session_id}/complete",
    response_model=SignatureCompleted,
    responses=ERROR_RESPONSES,
    summary="Finish a session with the token's signature",
    tags=["PDF"],
)
def complete_signature(session_id: str, payload: CompleteRequest = Body(...)):
    return _complete_one(session_id, _b64_bytes(payload.signature, "signature", "SIGNATURE_INVALID"))


BATCH_LIMIT = 50


def _batch_list(items: list, field: str) -> list:
    if not items:
        raise SignerError("DOCUMENT_INVALID", f"'{field}' must be a non-empty list")
    if len(items) > BATCH_LIMIT:
        raise SignerError("DOCUMENT_INVALID", f"batch is capped at {BATCH_LIMIT} documents")
    return items


@app.post(
    "/api/signatures/batch",
    response_model=BatchStarted,
    responses=ERROR_RESPONSES,
    summary="Start one session per document, sharing a certificate",
    tags=["PDF"],
)
def start_batch(payload: StartBatchRequest = Body(...)):
    """Many documents, one certificate. Caller signs every hash in one go, so
    the user sees one PIN prompt for the whole pile."""
    documents = _batch_list(payload.documents, "documents")
    cert_der = _b64_bytes(payload.certificate, "certificate", "CERT_INVALID")
    options = _options_dict(payload.options)
    timestamper = _request_timestamper(options)
    # Shared, so we ask the CA once for the batch instead of once per document.
    validation_context = _signing_validation_context()

    entries = []
    digest_algorithm = "sha256"
    for index, document in enumerate(documents):
        try:
            pdf_bytes = _document_bytes(document)
            state, to_sign_hash, digest_algorithm = SigningSession.start(
                pdf_bytes,
                cert_der,
                options,
                timestamper=timestamper,
                validation_context=validation_context,
                strict_ltv=config.strict_ltv,
                policy_dir=config.policy_dir,
            )
        except SignerError as exc:
            raise SignerError(exc.code, f"document {index}: {exc.message}") from None
        entries.append({
            "session_id": sessions.put(state.to_bytes()),
            "to_sign_hash": base64.b64encode(to_sign_hash).decode("ascii"),
        })

    return {
        "sessions": entries,
        "digest_algorithm": digest_algorithm,
        "expires_at": _expires_at(),
    }


@app.post(
    "/api/signatures/batch-complete",
    response_model=BatchCompleted,
    responses=ERROR_RESPONSES,
    summary="Finish a batch with the token's signatures",
    tags=["PDF"],
)
def complete_batch(payload: BatchCompleteRequest = Body(...)):
    items = _batch_list(payload.items, "items")
    results = []
    for index, item in enumerate(items):
        try:
            signature = _b64_bytes(item.signature, "signature", "SIGNATURE_INVALID")
            results.append(_complete_one(item.session_id, signature))
        except SignerError as exc:
            # Stop here. Whatever already finished stays finished.
            raise SignerError(exc.code, f"item {index}: {exc.message}") from None
    return {"documents": results}


def _sniff_media_type(data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data.lstrip()[:1] == b"<":
        return "application/xml"
    return "application/pkcs7-signature"  # detached CAdES (.p7s)


@app.get(
    "/api/documents/{document_id}",
    # Set so the spec does not also claim this returns JSON. It returns a file.
    response_class=Response,
    responses={
        200: {
            "description": "The signed document",
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "application/xml": {"schema": {"type": "string", "format": "binary"}},
                "application/pkcs7-signature": {
                    "schema": {"type": "string", "format": "binary"}
                },
            },
        },
        **ERROR_RESPONSES,
    },
    summary="Download a signed document",
    tags=["Documents"],
)
def get_document(document_id: str):
    try:
        data = documents.get(document_id)
    except Expired:
        raise SignerError("SESSION_EXPIRED", "document has expired") from None
    except Missing:
        # No document-specific code exists. This is the nearest one.
        raise SignerError("SESSION_NOT_FOUND", "no such document") from None
    return Response(content=data, media_type=_sniff_media_type(data))


@app.post(
    "/api/sign-server-side",
    response_model=ServerSideSigned,
    response_model_exclude_none=True,
    responses=ERROR_RESPONSES,
    summary="Sign a PDF with the server's own key",
    tags=["PDF"],
)
def sign_server_side(payload: SignServerSideRequest = Body(...)):
    if not config.p12_path:
        raise SignerError("INTERNAL", "server-side signing is not configured (set P12_PATH)")
    pdf_bytes = _document_bytes(payload.document)
    options = _options_dict(payload.options)
    signed_pdf = sign_with_p12(
        pdf_bytes,
        config.p12_path,
        config.p12_passphrase,
        options,
        timestamper=_request_timestamper(options),
        validation_context=_signing_validation_context(),
        policy_dir=config.policy_dir,
    )
    return {**_stored_document_response(signed_pdf), **_pdfa_fields(pdf_bytes, options)}


@app.post(
    "/api/validate",
    response_model=ValidationResult,
    responses=ERROR_RESPONSES,
    summary="Check the signatures on a PDF",
    tags=["PDF"],
)
def validate_document(payload: ValidateRequest = Body(...)):
    pdf_bytes = _document_bytes(payload.document)
    return {
        "signatures": validate(pdf_bytes, config.trust_dir),
        "pdfa": detect_pdfa(pdf_bytes),
    }


# ---- CAdES: sign any file, signature comes out separate as a .p7s ----


@app.post(
    "/api/cades/signatures",
    response_model=SessionStarted,
    response_model_exclude_none=True,
    responses=ERROR_RESPONSES,
    summary="Start a detached CAdES session over any file",
    tags=["CAdES"],
)
def start_cades(payload: StartSignatureRequest = Body(...)):
    data = _document_bytes(payload.document)
    cert_der = _b64_bytes(payload.certificate, "certificate", "CERT_INVALID")
    options = _options_dict(payload.options)

    state, to_sign_hash, digest_algorithm = CadesSession.start(
        data,
        cert_der,
        options,
        timestamper=_request_timestamper(options),
        policy_dir=config.policy_dir,
    )
    session_id = sessions.put(state.to_bytes())
    return {
        "session_id": session_id,
        "to_sign_hash": base64.b64encode(to_sign_hash).decode("ascii"),
        "digest_algorithm": digest_algorithm,
        "expires_at": _expires_at(),
    }


@app.post(
    "/api/cades/signatures/{session_id}/complete",
    response_model=StoredDocument,
    responses=ERROR_RESPONSES,
    summary="Finish a CAdES session, producing a .p7s",
    tags=["CAdES"],
)
def complete_cades(session_id: str, payload: CompleteRequest = Body(...)):
    signature = _b64_bytes(payload.signature, "signature", "SIGNATURE_INVALID")
    try:
        state = CadesState.from_bytes(_load_session(session_id))
    except SignerError:
        raise
    except Exception:
        raise SignerError("SESSION_NOT_FOUND", "no such session") from None

    p7s = CadesSession.complete(
        state, signature, timestamper=_timestamper(state.tsa_url or config.tsa_url)
    )
    sessions.delete(session_id)
    return _stored_document_response(p7s)


@app.post(
    "/api/cades/sign-server-side",
    response_model=StoredDocument,
    responses=ERROR_RESPONSES,
    summary="Produce a .p7s with the server's own key",
    tags=["CAdES"],
)
def cades_server_side(payload: SignServerSideRequest = Body(...)):
    if not config.p12_path:
        raise SignerError("INTERNAL", "server-side signing is not configured (set P12_PATH)")
    data = _document_bytes(payload.document)
    options = _options_dict(payload.options)
    p7s = sign_cades_with_p12(
        data,
        config.p12_path,
        config.p12_passphrase,
        options,
        timestamper=_request_timestamper(options),
        policy_dir=config.policy_dir,
    )
    return _stored_document_response(p7s)


# ---- XAdES: sign XML, signature goes inside it. Server key only ----


@app.post(
    "/api/xades/sign-server-side",
    response_model=StoredDocument,
    responses=ERROR_RESPONSES,
    summary="Sign XML in place with the server's own key",
    tags=["XAdES"],
)
def xades_server_side(payload: SignServerSideRequest = Body(...)):
    if not config.p12_path:
        raise SignerError("INTERNAL", "server-side signing is not configured (set P12_PATH)")
    xml_bytes = _document_bytes(payload.document)
    signed_xml = sign_xml_with_p12(
        xml_bytes, config.p12_path, config.p12_passphrase, _options_dict(payload.options)
    )
    return _stored_document_response(signed_xml)
