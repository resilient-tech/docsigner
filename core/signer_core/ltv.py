"""Key-free LTV augmentation of an already-signed PDF.

B-LT and B-LTA build on a finished B-T signature. Revocation data for the
signer and timestamp chains goes into the document security store (DSS), and
B-LTA adds a document-level archive timestamp on top. Both are incremental
updates over the signed bytes, so no private key is involved and the work can
happen after a token session completes.

Revocation source preference: pyhanko-certvalidator tries OCSP first whenever
the certificate carries an OCSP URL and falls back to CRLs only when OCSP
yields no good status. That default suits Indian CAs, whose CRLs run to
megabytes while an OCSP response is a couple of kilobytes; no extra fetcher
configuration is needed.
"""

import io

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.signers.pdf_signer import PdfTimeStamper
from pyhanko.sign.validation import async_add_validation_info
from pyhanko.sign.validation.dss import DocumentSecurityStore

from .errors import SignerError


async def async_augment(
    pdf_bytes: bytes,
    validation_context,
    *,
    timestamper=None,
    archive_timestamp: bool = False,
    md_algorithm: str = "sha256",
) -> bytes:
    """Upgrade the newest signature in ``pdf_bytes`` from B-T to B-LT/B-LTA.

    ``validation_context`` must be able to validate the signer's chain and,
    when it fetches, reach the CA's OCSP or CRL endpoints. Production callers
    pass a context from trust.build_validation_context(trust_dir,
    allow_fetching=True); tests inject one preloaded with offline CRL/OCSP
    data. With ``archive_timestamp`` a document timestamp from ``timestamper``
    is appended after the DSS update.
    """
    output = io.BytesIO(pdf_bytes)
    reader = PdfFileReader(output, strict=False)
    embedded_sig = reader.embedded_regular_signatures[-1]
    try:
        await async_add_validation_info(
            embedded_sig, validation_context, in_place=True
        )
    except Exception as exc:
        raise SignerError(
            "INTERNAL",
            f"could not collect revocation data for the signer chain: {exc}"
            " (check TRUST_DIR contents and OCSP/CRL reachability)",
        ) from None

    _require_revocation_info(output.getvalue())

    if archive_timestamp:
        writer = IncrementalPdfFileWriter(output, strict=False)
        try:
            await PdfTimeStamper(timestamper).async_timestamp_pdf(
                writer,
                md_algorithm,
                validation_context=validation_context,
                in_place=True,
            )
        except Exception as exc:
            raise SignerError(
                "INTERNAL", f"could not add the archive timestamp: {exc}"
            ) from None
    return output.getvalue()


def _require_revocation_info(pdf_bytes: bytes) -> None:
    """A B-LT DSS without any OCSP response or CRL is an empty promise.

    Soft-fail validation contexts tolerate unreachable revocation endpoints;
    this check turns that silence into a hard error.
    """
    dss = DocumentSecurityStore.read_dss(
        PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
    )
    if not (dss.ocsps or dss.crls):
        raise SignerError(
            "INTERNAL",
            "no OCSP response or CRL could be obtained for the signer chain;"
            " refusing to produce a B-LT signature without revocation data",
        )
