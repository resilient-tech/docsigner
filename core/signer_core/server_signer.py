"""One-shot signing with a server-held PKCS#12 key. No session dance."""

import io
import secrets

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers

from .appearance import build_appearance
from .errors import SignerError
from .profiles import Profile, build_metadata, check_requirements


def sign_with_p12(
    pdf_bytes: bytes,
    p12_path: str,
    passphrase: str | bytes | None = None,
    options: dict | None = None,
    *,
    timestamper=None,
    validation_context=None,
) -> bytes:
    options = options or {}
    profile = Profile.parse(options.get("profile"))
    check_requirements(profile, timestamper, validation_context)

    if isinstance(passphrase, str):
        passphrase = passphrase.encode("utf-8")
    try:
        signer = signers.SimpleSigner.load_pkcs12(p12_path, passphrase=passphrase)
    except Exception:
        signer = None
    if signer is None:
        raise SignerError(
            "INTERNAL", "could not load the server signing key (check P12_PATH/P12_PASSPHRASE)"
        )

    try:
        # strict=False: tolerate real-world PDFs with minor xref quirks (see session.py).
        writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
    except Exception:
        raise SignerError("DOCUMENT_INVALID", "document is not a readable PDF") from None

    field_name = options.get("field_name") or f"Signature-{secrets.token_hex(4)}"
    stamp_style, field_spec = build_appearance(options.get("appearance"), field_name)
    pdf_signer = signers.PdfSigner(
        build_metadata(options, profile, field_name, validation_context),
        signer=signer,
        timestamper=timestamper if profile.needs_timestamp else None,
        stamp_style=stamp_style,
        new_field_spec=field_spec,
    )
    try:
        output = pdf_signer.sign_pdf(writer)
    except SignerError:
        raise
    except Exception as exc:
        raise SignerError("DOCUMENT_INVALID", f"could not sign the PDF: {exc}") from None
    return output.getvalue()
