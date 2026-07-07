"""Key-free LTV augmentation of an already-signed PDF.

B-LT and B-LTA build on a finished B-T signature. Revocation data for the
signer and timestamp chains goes into the document security store (DSS), and
B-LTA adds a document-level archive timestamp on top. Both are incremental
updates over the signed bytes, so no private key is involved and the work can
happen after a token session completes.

Revocation source preference: the certvalidator fetcher tries OCSP first but
still collects CRLs along the way, and everything it caches would land in the
DSS. Indian CA CRLs run to megabytes while the OCSP responses total a few KB,
so after validation the collected revinfo is filtered: when every certificate
below its trust anchor has a good OCSP response, the CRLs are dropped and the
DSS carries OCSP only. CCA ESAIG 1.19.3 prefers OCSP over large CRLs, and
PAdES does not require both sources.
"""

import io

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.signers.pdf_signer import PdfTimeStamper
from pyhanko.sign.validation import async_add_validation_info, collect_validation_info
from pyhanko.sign.validation.dss import DocumentSecurityStore
from pyhanko_certvalidator import ValidationContext

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
        paths = await collect_validation_info(embedded_sig, validation_context)
        if archive_timestamp:
            async for ts_path in timestamper.validation_paths(validation_context):
                paths.append(ts_path)
        dss_context = _filtered_offline_context(validation_context, paths)
        await async_add_validation_info(embedded_sig, dss_context, in_place=True)
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
                validation_context=dss_context,
                in_place=True,
            )
        except Exception as exc:
            raise SignerError(
                "INTERNAL", f"could not add the archive timestamp: {exc}"
            ) from None
    return output.getvalue()


def dss_from_embedded_revinfo(pdf_bytes: bytes) -> bytes:
    """Copy a signature's pdfRevocationInfoArchival attribute into a DSS.

    CCA signatures carry revocation in that signed attribute (ESAIG 1.19), but
    Adobe's "LTV enabled" badge reads the document security store. This mirrors
    the same OCSP responses, CRLs, and certificates into a DSS with no network
    round trip, so the reliable revocation gathered at signing time is reused
    rather than re-fetched through a flaky OCSP responder.
    """
    reader = PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
    embedded_sig = reader.embedded_regular_signatures[-1]
    revinfo = _embedded_revinfo(embedded_sig)
    if revinfo is None:
        return pdf_bytes
    ocsps = list(revinfo["ocsp"]) if "ocsp" in revinfo else []
    crls = list(revinfo["crl"]) if "crl" in revinfo else []
    signed_data = embedded_sig.signed_data
    certs = [c.chosen for c in signed_data["certificates"] if c.name == "certificate"]

    output = io.BytesIO(pdf_bytes)
    DocumentSecurityStore.add_dss(
        output, embedded_sig.pkcs7_content.hex().encode("ascii"),
        certs=certs, ocsps=ocsps, crls=crls, force_write=True,
    )
    return output.getvalue()


def _embedded_revinfo(embedded_sig):
    for attr in embedded_sig.signer_info["signed_attrs"]:
        if attr["type"].dotted == "1.2.840.113583.1.1.8":
            return attr["values"][0]
    return None


def _filtered_offline_context(validation_context, paths) -> ValidationContext:
    """A non-fetching context holding only the revinfo the DSS should carry.

    async_add_validation_info and async_timestamp_pdf embed every OCSP
    response and CRL cached on the context they receive, so the filtering
    happens here: validate first against the caller's fetching context, then
    hand the DSS writers a context preloaded with the filtered revinfo. Trust
    anchors and gathered certificates carry over, so revalidation inside the
    writers stays offline.
    """
    ocsps = list(validation_context.ocsps)
    crls = list(validation_context.crls)
    needs_revinfo = set()
    for path in paths:
        needs_revinfo.update(_serials_below_anchor(path))
    if ocsps and crls and needs_revinfo <= _ocsp_good_serials(ocsps):
        crls = []
    return ValidationContext(
        trust_manager=validation_context.path_builder.trust_manager,
        certificate_registry=validation_context.certificate_registry,
        ocsps=ocsps,
        crls=crls,
        allow_fetching=False,
        revinfo_policy=validation_context.revinfo_policy,
    )


def _serials_below_anchor(path):
    """Serials of every certificate in a validation path except its anchor.

    Trust anchors need no revocation data (ESAIG 1.21: the root is verified
    by thumbprint, not revocation).
    """
    certs = list(path)
    return {cert.serial_number for cert in certs[1:]}


def _ocsp_good_serials(ocsps):
    """Serials confirmed 'good' by a successful OCSP response."""
    good = set()
    for resp in ocsps:
        if resp["response_status"].native != "successful":
            continue
        basic = resp["response_bytes"]["response"].parsed
        for single in basic["tbs_response_data"]["responses"]:
            if single["cert_status"].name == "good":
                good.add(single["cert_id"]["serial_number"].native)
    return good


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
