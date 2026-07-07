"""The endpoints from CONTRACTS.md section 1. Thin on purpose: all
signing logic lives in signer-core; this module only speaks HTTP."""

import base64
from datetime import datetime, timedelta, timezone

from fastapi import Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from signer_core import SessionState, SignerError, SigningSession, sign_with_p12, validate
from signer_core.cades import CadesSession, CadesState, sign_cades_with_p12
from signer_core.pdfa import detect_pdfa
from signer_core.trust import build_validation_context, make_timestamper, resolve_tsa_url
from signer_core.xades import sign_xml_with_p12

from .config import Config
from .store import Expired, FileStore, Missing

config = Config.from_env()

app = FastAPI(title="signer-server")
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


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "DOCUMENT_INVALID", "message": "malformed request body"}},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    # This handler runs in Starlette's outermost error middleware, outside
    # CORSMiddleware, so the header must be set by hand: without it browsers
    # report a 500 as a network failure instead of showing the error.
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL", "message": "internal server error"}},
        headers={"Access-Control-Allow-Origin": "*"},
    )


def _b64_bytes(payload: dict, field: str, error_code: str) -> bytes:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise SignerError(error_code, f"'{field}' must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except Exception:
        raise SignerError(error_code, f"'{field}' is not valid base64") from None


def _document_bytes(payload: dict) -> bytes:
    pdf_bytes = _b64_bytes(payload, "document", "DOCUMENT_INVALID")
    if len(pdf_bytes) > config.max_pdf_bytes:
        raise SignerError(
            "DOCUMENT_INVALID", f"document exceeds the {config.max_pdf_mb} MB limit"
        )
    return pdf_bytes


def _signing_validation_context():
    if config.trust_dir:
        # "require" so B-LT/B-LTA embed revocation for the whole chain; a partial
        # DSS reads as "not LTV enabled" in Adobe. Only affects LTV completion,
        # which is the sole caller that gathers revocation.
        return build_validation_context(
            config.trust_dir, allow_fetching=True, revocation_mode="require"
        )
    return None


def _stored_document_response(signed_pdf: bytes) -> dict:
    document_id = documents.put(signed_pdf)
    return {"document_id": document_id, "download_url": f"/api/documents/{document_id}"}


def _request_timestamper(options: dict):
    """The TSA for this request: options.tsa (a registry name) or the default."""
    return make_timestamper(resolve_tsa_url(options.get("tsa"), config.tsa_url))


def _pdfa_fields(pdf_bytes: bytes, options: dict) -> dict:
    """Additive response fields describing the document's PDF/A claim."""
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


@app.post("/api/signatures")
def start_signature(payload: dict = Body(...)):
    pdf_bytes = _document_bytes(payload)
    cert_der = _b64_bytes(payload, "certificate", "CERT_INVALID")
    options = payload.get("options") or {}

    state, to_sign_hash, digest_algorithm = SigningSession.start(
        pdf_bytes,
        cert_der,
        options,
        timestamper=_request_timestamper(options),
        validation_context=_signing_validation_context(),
    )
    session_id = sessions.put(state.to_bytes())
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=config.session_ttl_seconds)
    return {
        "session_id": session_id,
        "to_sign_hash": base64.b64encode(to_sign_hash).decode("ascii"),
        "digest_algorithm": digest_algorithm,
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        **_pdfa_fields(pdf_bytes, options),
    }


def _load_session(session_id: str) -> bytes:
    try:
        return sessions.get(session_id)
    except Expired:
        raise SignerError("SESSION_EXPIRED", "session has expired") from None
    except Missing:
        raise SignerError("SESSION_NOT_FOUND", "no such session") from None


@app.post("/api/signatures/{session_id}/complete")
def complete_signature(session_id: str, payload: dict = Body(...)):
    signature = _b64_bytes(payload, "signature", "SIGNATURE_INVALID")
    try:
        state = SessionState.from_bytes(_load_session(session_id))
    except SignerError:
        raise
    except Exception:
        # A CAdES session id, or a corrupt blob: not a PDF signing session.
        raise SignerError("SESSION_NOT_FOUND", "no such session") from None

    signed_pdf = SigningSession.complete(
        state,
        signature,
        timestamper=make_timestamper(state.tsa_url or config.tsa_url),
        validation_context=_signing_validation_context(),
    )
    # Single-use: consumed on success; a failed attempt may be retried.
    sessions.delete(session_id)
    return _stored_document_response(signed_pdf)


def _sniff_media_type(data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data.lstrip()[:1] == b"<":
        return "application/xml"
    return "application/pkcs7-signature"  # detached CAdES (.p7s)


@app.get("/api/documents/{document_id}")
def get_document(document_id: str):
    try:
        data = documents.get(document_id)
    except Expired:
        raise SignerError("SESSION_EXPIRED", "document has expired") from None
    except Missing:
        # The contract defines no document-specific code; this is the closest fit.
        raise SignerError("SESSION_NOT_FOUND", "no such document") from None
    return Response(content=data, media_type=_sniff_media_type(data))


@app.post("/api/sign-server-side")
def sign_server_side(payload: dict = Body(...)):
    if not config.p12_path:
        raise SignerError("INTERNAL", "server-side signing is not configured (set P12_PATH)")
    pdf_bytes = _document_bytes(payload)
    options = payload.get("options") or {}
    signed_pdf = sign_with_p12(
        pdf_bytes,
        config.p12_path,
        config.p12_passphrase,
        options,
        timestamper=_request_timestamper(options),
        validation_context=_signing_validation_context(),
    )
    return {**_stored_document_response(signed_pdf), **_pdfa_fields(pdf_bytes, options)}


@app.post("/api/validate")
def validate_document(payload: dict = Body(...)):
    pdf_bytes = _document_bytes(payload)
    return {
        "signatures": validate(pdf_bytes, config.trust_dir),
        "pdfa": detect_pdfa(pdf_bytes),
    }


# ---- CAdES: detached .p7s over any file (CONTRACTS.md section 1, CAdES) ----


@app.post("/api/cades/signatures")
def start_cades(payload: dict = Body(...)):
    data = _document_bytes(payload)
    cert_der = _b64_bytes(payload, "certificate", "CERT_INVALID")
    options = payload.get("options") or {}

    state, to_sign_hash, digest_algorithm = CadesSession.start(
        data, cert_der, options, timestamper=_request_timestamper(options)
    )
    session_id = sessions.put(state.to_bytes())
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=config.session_ttl_seconds)
    return {
        "session_id": session_id,
        "to_sign_hash": base64.b64encode(to_sign_hash).decode("ascii"),
        "digest_algorithm": digest_algorithm,
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@app.post("/api/cades/signatures/{session_id}/complete")
def complete_cades(session_id: str, payload: dict = Body(...)):
    signature = _b64_bytes(payload, "signature", "SIGNATURE_INVALID")
    try:
        state = CadesState.from_bytes(_load_session(session_id))
    except SignerError:
        raise
    except Exception:
        raise SignerError("SESSION_NOT_FOUND", "no such session") from None

    p7s = CadesSession.complete(
        state, signature, timestamper=make_timestamper(state.tsa_url or config.tsa_url)
    )
    sessions.delete(session_id)
    return _stored_document_response(p7s)


@app.post("/api/cades/sign-server-side")
def cades_server_side(payload: dict = Body(...)):
    if not config.p12_path:
        raise SignerError("INTERNAL", "server-side signing is not configured (set P12_PATH)")
    data = _document_bytes(payload)
    options = payload.get("options") or {}
    p7s = sign_cades_with_p12(
        data,
        config.p12_path,
        config.p12_passphrase,
        options,
        timestamper=_request_timestamper(options),
    )
    return _stored_document_response(p7s)


# ---- XAdES: enveloped XML signature, server-held key only ----


@app.post("/api/xades/sign-server-side")
def xades_server_side(payload: dict = Body(...)):
    if not config.p12_path:
        raise SignerError("INTERNAL", "server-side signing is not configured (set P12_PATH)")
    xml_bytes = _document_bytes(payload)
    signed_xml = sign_xml_with_p12(
        xml_bytes, config.p12_path, config.p12_passphrase, payload.get("options") or {}
    )
    return _stored_document_response(signed_xml)
