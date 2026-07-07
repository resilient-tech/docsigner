"""Key-free LTV augmentation of an already-signed PDF.

B-LT and B-LTA build on a finished B-T signature. Revocation data for the
signer and timestamp chains goes into the document security store (DSS), and
B-LTA adds a document-level archive timestamp on top. Both are incremental
updates over the signed bytes, so no private key is involved and the work can
happen after a token session completes.

Under strict LTV (the default) the DSS carries every OCSP response and CRL the
certvalidator fetcher gathered while validating the chain. The fetcher is
OCSP-first, so it pulls a CRL only when OCSP cannot answer, and one Indian CA
case makes that happen: a Capricorn end-entity is answered by a CA-level OCSP
responder that RFC 6960 does not authorise for the leaf, so the validator falls
back to the sub-CA's CRL. Keeping that CRL is what lets a reader validate the
chain offline. With strict LTV off, those CRLs are dropped once OCSP covers the
chain: a smaller DSS, at the cost of reading as not LTV enabled where a
responder lacks id-pkix-ocsp-nocheck.
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
    strict_ltv: bool = True,
) -> bytes:
    """Upgrade the newest signature in ``pdf_bytes`` from B-T to B-LT/B-LTA.

    ``validation_context`` must be able to validate the signer's chain and,
    when it fetches, reach the CA's OCSP or CRL endpoints. Production callers
    pass a context from trust.build_validation_context(trust_dir,
    allow_fetching=True); tests inject one preloaded with offline CRL/OCSP
    data. With ``archive_timestamp`` a document timestamp from ``timestamper``
    is appended after the DSS update.

    ``strict_ltv`` (default) keeps every gathered CRL and re-validates the chain,
    so the DSS verifies offline (Adobe reports LTV enabled) or signing aborts.
    Turning it off drops CRLs once OCSP covers the chain: a smaller DSS that can
    read as not LTV enabled where a responder lacks id-pkix-ocsp-nocheck.
    """
    output = io.BytesIO(pdf_bytes)
    reader = PdfFileReader(output, strict=False)
    embedded_sig = reader.embedded_regular_signatures[-1]
    try:
        paths = await collect_validation_info(embedded_sig, validation_context)
        if archive_timestamp:
            # Gather the archive timestamp chain's revocation as well, so the DSS
            # covers it before the timestamp is applied.
            async for ts_path in timestamper.validation_paths(validation_context):
                paths.append(ts_path)
        ocsps, crls = _select_revinfo(validation_context, paths, strict_ltv)
        if strict_ltv:
            # async_add_validation_info re-validates the chain against the offline
            # copy and aborts if the revinfo is short, so a partial (not LTV) DSS
            # is never written silently.
            dss_context = _preloaded_context(validation_context, ocsps, crls)
            await async_add_validation_info(embedded_sig, dss_context, in_place=True)
        else:
            # Embed the OCSP-first revinfo directly, skipping that re-validation, so
            # a smaller DSS is produced even for a chain whose responder would need
            # its CRL to verify.
            DocumentSecurityStore.add_dss(
                output,
                embedded_sig.pkcs7_content.hex().encode("ascii"),
                paths=paths,
                ocsps=ocsps,
                crls=crls,
                force_write=True,
                strict=False,
            )
            dss_context = None
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
            # Strict mode validates the archive timestamp and adds its revinfo
            # through dss_context; otherwise that chain's revinfo is already above.
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


def dss_from_embedded_revinfo(pdf_bytes: bytes, extra_certs=None) -> bytes:
    """Copy a signature's pdfRevocationInfoArchival attribute into a DSS.

    CCA signatures carry revocation in that signed attribute (ESAIG 1.19), but
    Adobe's "LTV enabled" badge reads the document security store. This mirrors
    the same OCSP responses, CRLs, and certificates into a DSS with no network
    round trip, so the reliable revocation gathered at signing time is reused
    rather than re-fetched through a flaky OCSP responder.

    The CMS carries only the signer certificate, so ``extra_certs`` supplies the
    rest of the chain (the sub-CA is absent from both the CMS and the OCSP
    bundles); without it a reader cannot build the path and Adobe reports the
    signature as not LTV enabled.
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
    certs += list(extra_certs or [])

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


def _select_revinfo(validation_context, paths, strict_ltv):
    """The (ocsps, crls) the DSS or signed attribute should carry.

    strict_ltv keeps every gathered CRL, so a chain whose OCSP responder is not
    RFC 6960 authorised for the leaf still verifies offline (Adobe LTV). Off, the
    CRLs are dropped once every certificate below its anchor has a good OCSP
    response: smaller, but read as not LTV enabled where a responder lacks
    id-pkix-ocsp-nocheck. The fetcher is OCSP-first, so it only pulls a CRL when
    OCSP cannot answer; a well-behaved responder stays OCSP-only either way.
    """
    ocsps = list(validation_context.ocsps)
    crls = list(validation_context.crls)
    if strict_ltv:
        return ocsps, crls
    needs = set()
    for path in paths:
        needs.update(_serials_below_anchor(path))
    if ocsps and crls and needs <= _ocsp_good_serials(ocsps):
        crls = []
    return ocsps, crls


def _preloaded_context(validation_context, ocsps, crls) -> ValidationContext:
    """A non-fetching context holding the chosen revinfo for the DSS writers.

    async_add_validation_info and async_timestamp_pdf embed the revinfo cached on
    the context they receive, so they revalidate offline against exactly this
    set. Trust anchors and gathered certificates carry over.
    """
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
