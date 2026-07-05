"""The five endpoints from CONTRACTS.md section 1. Thin on purpose: all
signing logic lives in signer-core; this module only speaks HTTP."""

import base64
from datetime import datetime, timedelta, timezone

from fastapi import Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from signer_core import SessionState, SignerError, SigningSession, sign_with_p12, validate
from signer_core.trust import build_validation_context, make_timestamper

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
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL", "message": "internal server error"}},
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
        return build_validation_context(config.trust_dir, allow_fetching=True)
    return None


def _stored_document_response(signed_pdf: bytes) -> dict:
    document_id = documents.put(signed_pdf)
    return {"document_id": document_id, "download_url": f"/api/documents/{document_id}"}


@app.post("/api/signatures")
def start_signature(payload: dict = Body(...)):
    pdf_bytes = _document_bytes(payload)
    cert_der = _b64_bytes(payload, "certificate", "CERT_INVALID")
    options = payload.get("options") or {}

    state, to_sign_hash, digest_algorithm = SigningSession.start(
        pdf_bytes,
        cert_der,
        options,
        timestamper=make_timestamper(config.tsa_url),
        validation_context=_signing_validation_context(),
    )
    session_id = sessions.put(state.to_bytes())
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=config.session_ttl_seconds)
    return {
        "session_id": session_id,
        "to_sign_hash": base64.b64encode(to_sign_hash).decode("ascii"),
        "digest_algorithm": digest_algorithm,
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@app.post("/api/signatures/{session_id}/complete")
def complete_signature(session_id: str, payload: dict = Body(...)):
    signature = _b64_bytes(payload, "signature", "SIGNATURE_INVALID")
    try:
        raw_state = sessions.get(session_id)
    except Expired:
        raise SignerError("SESSION_EXPIRED", "session has expired") from None
    except Missing:
        raise SignerError("SESSION_NOT_FOUND", "no such session") from None

    signed_pdf = SigningSession.complete(
        SessionState.from_bytes(raw_state),
        signature,
        timestamper=make_timestamper(config.tsa_url),
    )
    # Single-use: consumed on success; a failed attempt may be retried.
    sessions.delete(session_id)
    return _stored_document_response(signed_pdf)


@app.get("/api/documents/{document_id}")
def get_document(document_id: str):
    try:
        pdf_bytes = documents.get(document_id)
    except Expired:
        raise SignerError("SESSION_EXPIRED", "document has expired") from None
    except Missing:
        # The contract defines no document-specific code; this is the closest fit.
        raise SignerError("SESSION_NOT_FOUND", "no such document") from None
    return Response(content=pdf_bytes, media_type="application/pdf")


@app.post("/api/sign-server-side")
def sign_server_side(payload: dict = Body(...)):
    if not config.p12_path:
        raise SignerError("INTERNAL", "server-side signing is not configured (set P12_PATH)")
    pdf_bytes = _document_bytes(payload)
    signed_pdf = sign_with_p12(
        pdf_bytes,
        config.p12_path,
        config.p12_passphrase,
        payload.get("options") or {},
        timestamper=make_timestamper(config.tsa_url),
        validation_context=_signing_validation_context(),
    )
    return _stored_document_response(signed_pdf)


@app.post("/api/validate")
def validate_document(payload: dict = Body(...)):
    pdf_bytes = _document_bytes(payload)
    return {"signatures": validate(pdf_bytes, config.trust_dir)}
