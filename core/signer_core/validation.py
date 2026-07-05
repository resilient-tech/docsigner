"""Signature validation shaped to the /api/validate contract."""

import asyncio
import io
from datetime import timezone

from cryptography import x509 as pyca_x509
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import async_validate_pdf_signature

from .errors import SignerError
from .trust import build_validation_context


def validate(pdf_bytes: bytes, trust_dir=None) -> list[dict]:
    """One dict per embedded signature, matching the contract's response shape.

    Untrusted or self-signed certificates never raise; they come back with the
    flags reported honestly (trusted=False and so on).
    """
    return asyncio.run(_validate(pdf_bytes, trust_dir))


async def _validate(pdf_bytes, trust_dir):
    try:
        reader = PdfFileReader(io.BytesIO(pdf_bytes))
        embedded = list(reader.embedded_signatures)
    except Exception:
        raise SignerError("DOCUMENT_INVALID", "document is not a readable PDF") from None
    return [await _validate_one(emb, trust_dir) for emb in embedded]


async def _validate_one(emb, trust_dir):
    result = {
        "field_name": emb.field_name,
        "valid": False,
        "intact": False,
        "trusted": False,
        "signer": None,
        "signing_time": None,
        "profile_notes": None,
    }
    if emb.signer_cert is not None:
        subject = pyca_x509.load_der_x509_certificate(emb.signer_cert.dump()).subject
        result["signer"] = subject.rfc4514_string()

    try:
        # A fresh context per signature; contexts accumulate state.
        status = await async_validate_pdf_signature(
            emb, signer_validation_context=build_validation_context(trust_dir)
        )
    except Exception as exc:
        result["profile_notes"] = f"validation failed: {exc}"
        return result

    result["valid"] = bool(status.valid)
    result["intact"] = bool(status.intact)
    result["trusted"] = bool(status.trusted)
    signing_time = status.signer_reported_dt or emb.self_reported_timestamp
    if signing_time is not None:
        result["signing_time"] = signing_time.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    result["profile_notes"] = status.summary()
    return result
