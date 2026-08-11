"""Read a signed PDF back and say whether it holds up."""

import asyncio
import io
from datetime import timezone

from cryptography import x509 as pyca_x509
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.diff_analysis import ModificationLevel
from pyhanko.sign.validation import (
    async_validate_pdf_signature,
    async_validate_pdf_timestamp,
)

from .errors import SignerError
from .trust import build_validation_context


def validate(pdf_bytes: bytes, trust_dir=None) -> list[dict]:
    """One entry per signature on the file.

    A bad or unknown signer is not an error. It comes back reported honestly.
    """
    return asyncio.run(_validate(pdf_bytes, trust_dir))


async def _validate(pdf_bytes, trust_dir):
    try:
        # Lenient, same reason as pdf_sign.py.
        reader = PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
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
        "modifications_ok": None,
        "signer": None,
        "signing_time": None,
        "profile_notes": None,
    }
    if emb.signer_cert is not None:
        subject = pyca_x509.load_der_x509_certificate(emb.signer_cert.dump()).subject
        result["signer"] = subject.rfc4514_string()

    try:
        # A fresh one per signature. They pick up state as they go.
        context = build_validation_context(trust_dir)
        if emb.sig_object_type == "/DocTimeStamp":
            # This one is a timestamp, not a signature. Check it as what it is.
            status = await async_validate_pdf_timestamp(emb, validation_context=context)
        else:
            status = await async_validate_pdf_signature(
                emb, signer_validation_context=context
            )
    except Exception as exc:
        result["profile_notes"] = f"validation failed: {exc}"
        return result

    result["valid"] = bool(status.valid)
    result["intact"] = bool(status.intact)
    result["trusted"] = bool(status.trusted)
    # "intact" only means the signed bytes did not move. Things may legally be
    # added after signing (another signature, a timestamp), but the content may
    # not be edited. Report that separately, so a tampered file cannot hide
    # behind the other three flags all being true.
    mod_level = getattr(status, "modification_level", None)
    if mod_level is not None:
        result["modifications_ok"] = (
            mod_level is not ModificationLevel.OTHER
            and getattr(status, "docmdp_ok", None) is not False
        )
    signing_time = getattr(status, "signer_reported_dt", None) or emb.self_reported_timestamp
    if signing_time is not None:
        result["signing_time"] = signing_time.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    result["profile_notes"] = status.summary()
    return result
