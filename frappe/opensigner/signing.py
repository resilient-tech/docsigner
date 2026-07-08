"""The one signing ceremony. Every entry point — form button, bulk list
action, auto-sign on submit — routes through prepare() and finalize(); token
and server-key paths differ only in who produces the signature bytes.

Gates (enabled, submitted, print permission, role) live in prepare(), so a
fix here fixes every caller.
"""

import base64
import hashlib
import json
import secrets

import frappe
from cryptography import x509 as pyca_x509
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from frappe import _
from frappe.utils import get_url
from frappe.utils.file_manager import save_file

from signer_core import SessionState, SignerError, SigningSession, sign_with_p12
from signer_core.trust import build_validation_context, make_timestamper, resolve_tsa_url

# Safety constants, not settings (mirrors CONTRACTS.md batch cap).
BATCH_CAP = 50
SESSION_TTL_SECONDS = 900
_CACHE_PREFIX = "opensigner:session:"

_POSITIONS = {
    "Bottom Right": "bottom-right",
    "Bottom Left": "bottom-left",
    "Top Right": "top-right",
    "Top Left": "top-left",
}
_STAMP_SIZE = [220, 60]  # points; wide enough for name + details + QR panel


# --- the common front half -------------------------------------------------


def prepare(doctype: str, name: str, print_format: str) -> dict:
    """Render the print format and build signing options. Returns a context
    dict consumed by the token and server-key paths."""
    doc = frappe.get_doc(doctype, name)
    pf = frappe.get_doc("Print Format", print_format)
    assert_can_sign(doc, pf)

    pdf = frappe.get_print(doctype, name, print_format, as_pdf=True)
    code = secrets.token_urlsafe(18) if pf.opensigner_qr else None
    options = {
        "profile": pf.opensigner_profile or settings().default_profile,
        "appearance": _appearance(pf, code),
    }
    return {"doc": doc, "pf": pf, "pdf": pdf, "options": options, "code": code}


def assert_can_sign(doc, pf):
    """Every gate in one place. Raises frappe exceptions with user-facing text."""
    if not pf.get("opensigner_enabled"):
        frappe.throw(_("Digital signature is not enabled on Print Format {0}").format(pf.name))
    if pf.doc_type != doc.doctype:
        frappe.throw(_("Print Format {0} does not apply to {1}").format(pf.name, doc.doctype))
    if doc.meta.is_submittable and doc.docstatus != 1:
        frappe.throw(_("Submit the document before signing it"))
    if not frappe.has_permission(doc=doc, ptype="print"):
        frappe.throw(_("You need print permission on {0} to sign it").format(doc.name),
                     frappe.PermissionError)
    role = pf.get("opensigner_signer_role")
    if role and role not in frappe.get_roles():
        frappe.throw(_("Signing this print format needs the {0} role").format(role),
                     frappe.PermissionError)


def _appearance(pf, code):
    """The contract's appearance object, built from Print Format fields."""
    style = pf.get("opensigner_style") or "Handwritten"
    if style == "Invisible":
        return None

    s = settings()
    appearance = {"page": max(int(pf.get("opensigner_page") or 1), 1) - 1}
    position = pf.get("opensigner_position") or "Bottom Right"
    if position == "Custom Box":
        try:
            box = json.loads(pf.get("opensigner_box") or "")
            assert isinstance(box, list) and len(box) == 4
            appearance["box"] = box
        except Exception:
            frappe.throw(_("Custom Box must be [x1, y1, x2, y2] in PDF points"))
    else:
        appearance["position"] = _POSITIONS[position]
        appearance["size"] = _STAMP_SIZE

    if style == "Handwritten":
        appearance["style"] = "handwritten"
        appearance["capitalize"] = bool(s.handwritten_capitalize)
        appearance["bold"] = bool(s.handwritten_bold)
        # name intentionally omitted: signer-core uses the certificate CN,
        # which is the name the signature legally carries.
    elif style == "Image":
        image_url = pf.get("opensigner_signature_image")
        if not image_url:
            frappe.throw(_("Print Format {0} uses the Image style but has no Signature Image").format(pf.name))
        content = frappe.get_doc("File", {"file_url": image_url}).get_content()
        if isinstance(content, str):
            content = content.encode("latin-1")
        appearance["image"] = base64.b64encode(content).decode("ascii")

    if code:
        appearance["qr_url"] = verification_url(code)
    return appearance


# --- token path (browser extension signs the hash) --------------------------


def token_start(doctype, name, print_format, certificate_b64) -> dict:
    ctx = prepare(doctype, name, print_format)
    try:
        cert_der = base64.b64decode(certificate_b64, validate=True)
    except Exception:
        frappe.throw(_("certificate must be base64 DER"))

    state, to_sign_hash, digest_algorithm = _core(
        SigningSession.start, ctx["pdf"], cert_der, ctx["options"],
        timestamper=_timestamper(), validation_context=_validation_context(),
    )
    session_id = secrets.token_urlsafe(24)
    frappe.cache().set_value(
        _CACHE_PREFIX + session_id,
        json.dumps({
            "state": base64.b64encode(state.to_bytes()).decode("ascii"),
            "doctype": doctype, "name": name, "print_format": print_format,
            "code": ctx["code"], "user": frappe.session.user,
        }),
        expires_in_sec=SESSION_TTL_SECONDS,
    )
    return {
        "session_id": session_id,
        "to_sign_hash": base64.b64encode(to_sign_hash).decode("ascii"),
        "digest_algorithm": digest_algorithm,
    }


def token_complete(session_id, signature_b64) -> dict:
    key = _CACHE_PREFIX + str(session_id)
    raw = frappe.cache().get_value(key)
    if not raw:
        frappe.throw(_("Signing session expired or already used — start again"))
    payload = json.loads(raw)
    if payload["user"] != frappe.session.user:
        # Sessions are single-user: the hash was derived for this signer.
        frappe.throw(_("This signing session belongs to another user"), frappe.PermissionError)

    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception:
        frappe.throw(_("signature must be base64"))

    state = SessionState.from_bytes(base64.b64decode(payload["state"]))
    signed_pdf = _core(
        SigningSession.complete, state, signature,
        timestamper=make_timestamper(state.tsa_url or _tsa_url()),
        validation_context=_validation_context(),
    )
    frappe.cache().delete_value(key)  # single-use, consumed on success only

    doc = frappe.get_doc(payload["doctype"], payload["name"])
    pf = frappe.get_doc("Print Format", payload["print_format"])
    audit = _audit_record(state.cert_der, state.profile, state.digest_algorithm,
                          state.field_name, signed_pdf)
    return finalize(doc, pf, signed_pdf, audit, payload["code"])


# --- server-key path ---------------------------------------------------------


def server_sign(doctype, name, print_format) -> dict:
    ctx = prepare(doctype, name, print_format)
    s = settings()
    if not s.p12_file:
        frappe.throw(_("Upload a PKCS#12 key file in OpenSigner Settings first"))
    p12_path = frappe.get_doc("File", {"file_url": s.p12_file}).get_full_path()
    password = s.get_password("p12_password", raise_exception=False) or None

    signed_pdf = _core(
        sign_with_p12, ctx["pdf"], p12_path, password, ctx["options"],
        timestamper=_timestamper(), validation_context=_validation_context(),
    )
    cert = _p12_cert(p12_path, password)
    audit = _audit_record(cert.public_bytes(Encoding.DER),
                          ctx["options"]["profile"], "sha256", "", signed_pdf)
    return finalize(ctx["doc"], ctx["pf"], signed_pdf, audit, ctx["code"])


def server_sign_job(doctype, name, print_format):
    """Background job body for auto-sign; failures land in the Error Log with
    a pointer back to the document."""
    try:
        server_sign(doctype, name, print_format)
    except Exception:
        frappe.log_error(
            title=f"OpenSigner auto-sign failed: {doctype} {name}",
            message=frappe.get_traceback(),
        )


# --- the common back half ----------------------------------------------------


def finalize(doc, pf, signed_pdf: bytes, audit: dict, code) -> dict:
    file_doc = save_file(
        f"{frappe.scrub(doc.name)}-{frappe.scrub(pf.name)}-signed.pdf",
        signed_pdf, doc.doctype, doc.name, is_private=1,
    )
    log = frappe.get_doc({
        "doctype": "Signature Log",
        "ref_doctype": doc.doctype,
        "ref_name": doc.name,
        "print_format": pf.name,
        "signer": frappe.session.user,
        "signed_file": file_doc.file_url,
        "certificate_subject": audit["signer"],
        "certificate_serial": audit["certificate_serial"],
        "certificate_issuer": audit["certificate_issuer"],
        "profile": audit["profile"],
        "digest_algorithm": audit["digest_algorithm"],
        "field_name": audit["field_name"],
        "document_sha256": audit["document_sha256"],
        "verification_code": code,
        "audit_json": json.dumps(audit, indent=1),
    })
    log.insert(ignore_permissions=True)

    doc.add_comment(
        "Comment",
        _("Digitally signed ({0}) by {1} — <a href='{2}'>signed PDF</a>").format(
            pf.name, audit["signer"], file_doc.file_url
        ),
    )
    result = {"file_url": file_doc.file_url, "file_name": file_doc.file_name, "log": log.name}
    if code:
        result["verification_url"] = verification_url(code)
    return result


# --- shared plumbing ----------------------------------------------------------


def settings():
    return frappe.get_cached_doc("OpenSigner Settings")


def verification_url(code: str) -> str:
    base = (settings().verify_base_url or get_url()).rstrip("/")
    return f"{base}/os_verify?code={code}"


def _tsa_url():
    s = settings()
    return resolve_tsa_url(s.tsa or None, s.tsa_url or None)


def _timestamper():
    return make_timestamper(_tsa_url())


def _validation_context():
    trust_dir = settings().trust_dir
    if trust_dir:
        # "require" so LTV profiles embed revocation for the whole chain; a
        # partial DSS reads as "not LTV enabled" in Adobe (see signer-server).
        return build_validation_context(trust_dir, allow_fetching=True,
                                        revocation_mode="require")
    return None


def _core(fn, *args, **kwargs):
    """signer-core call with its errors translated for the desk."""
    try:
        return fn(*args, **kwargs)
    except SignerError as err:
        frappe.throw(_("Signing failed ({0}): {1}").format(err.code, err.message))


def _audit_record(cert_der: bytes, profile, digest_algorithm, field_name,
                  signed_pdf: bytes) -> dict:
    """Machine-readable completion record, same shape as CONTRACTS.md §1."""
    cert = pyca_x509.load_der_x509_certificate(cert_der)
    return {
        "signer": cert.subject.rfc4514_string(),
        "certificate_serial": str(cert.serial_number),
        "certificate_issuer": cert.issuer.rfc4514_string(),
        "profile": profile,
        "digest_algorithm": digest_algorithm,
        "field_name": field_name,
        "document_sha256": hashlib.sha256(signed_pdf).hexdigest(),
        "completed_at": frappe.utils.now_datetime().astimezone().isoformat(),
    }


def _p12_cert(p12_path, password):
    with open(p12_path, "rb") as f:
        raw = f.read()
    pw = password.encode() if isinstance(password, str) else password
    _key, cert, _extra = pkcs12.load_key_and_certificates(raw, pw)
    return cert
