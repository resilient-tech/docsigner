"""Make a signed PDF last. Proof the certificate was alive, plus a timestamp.

No key needed here, so this runs after the token is long gone. It bolts onto a
finished B-T signature.

strict (the default) keeps every proof gathered, so a reader can check the file
offline years later. Turn it off for a smaller file, at the cost of Adobe
sometimes not showing the LTV badge.
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
    """Upgrade the newest signature in the file to a long-term one.

    Needs to reach the CA to ask whether the chain is still good.
    """
    output = io.BytesIO(pdf_bytes)
    reader = PdfFileReader(output, strict=False)
    embedded_sig = reader.embedded_regular_signatures[-1]
    try:
        paths = await collect_validation_info(embedded_sig, validation_context)
        if archive_timestamp:
            # Cover the timestamp's own chain too, before stamping.
            async for ts_path in timestamper.validation_paths(validation_context):
                paths.append(ts_path)
        ocsps, crls = _select_revinfo(validation_context, paths, strict_ltv)
        if strict_ltv:
            # This path rechecks the whole chain offline and stops if anything is
            # missing, so we never quietly write a half-done file.
            dss_context = _preloaded_context(validation_context, ocsps, crls)
            await async_add_validation_info(embedded_sig, dss_context, in_place=True)
        else:
            # Write what we have and skip the recheck. Smaller file.
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
            # Strict mode checks the new timestamp too. The other path already
            # gathered that chain above.
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
    """Copy the proof India puts inside the signature to where Adobe looks.

    Same bytes, no refetch. `extra_certs` fills in the middle of the chain,
    which the signature does not carry and a reader cannot walk without.
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
    """Which proofs to keep.

    Strict keeps the big revocation lists as well, because some CAs (Capricorn
    for one) answer the leaf from a responder that a strict reader will not
    accept, and only the list covers it. Loose drops them once every certificate
    has a good short answer.
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
    """The chosen proofs, wrapped so the writers use exactly these and go nowhere."""
    return ValidationContext(
        trust_manager=validation_context.path_builder.trust_manager,
        certificate_registry=validation_context.certificate_registry,
        ocsps=ocsps,
        crls=crls,
        allow_fetching=False,
        revinfo_policy=validation_context.revinfo_policy,
    )


def _serials_below_anchor(path):
    """Everything in the chain except the root. A root needs no revocation proof."""
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
    """Refuse a long-term signature carrying no proof. That would be an empty claim."""
    dss = DocumentSecurityStore.read_dss(
        PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
    )
    if not (dss.ocsps or dss.crls):
        raise SignerError(
            "INTERNAL",
            "no OCSP response or CRL could be obtained for the signer chain;"
            " refusing to produce a B-LT signature without revocation data",
        )
