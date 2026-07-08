"""Whitelisted surface for sign.js and the verify page. Thin: parsing and
permission-safe reads here, every ceremony in signing.py."""

import json

import frappe
from frappe import _

from opensigner import signing


@frappe.whitelist()
def get_sign_context(doctype: str, name: str) -> dict:
    """What the form button needs: enabled print formats, whether this user
    can sign each, and the latest signature."""
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")

    contexts = []
    for pf_name in frappe.get_all(
        "Print Format", filters={"doc_type": doctype, "opensigner_enabled": 1}, pluck="name"
    ):
        pf = frappe.get_cached_doc("Print Format", pf_name)
        try:
            signing.assert_can_sign(doc, pf)
            can_sign, why_not = True, None
        except Exception as err:
            can_sign, why_not = False, str(getattr(err, "message", err))
        contexts.append({
            "print_format": pf.name,
            "mode": pf.opensigner_mode or "Token (user signs)",
            "style": pf.opensigner_style or "Handwritten",
            "qr": bool(pf.opensigner_qr),
            "can_sign": can_sign,
            "why_not": why_not,
        })

    last = frappe.get_all(
        "Signature Log",
        filters={"ref_doctype": doctype, "ref_name": name},
        fields=["name", "signer", "certificate_subject", "print_format",
                "signed_file", "verification_code", "creation"],
        order_by="creation desc",
        limit=1,
        ignore_permissions=True,  # the signed-state headline is not a secret to doc readers
    )
    last_log = last[0] if last else None
    if last_log and last_log.verification_code:
        last_log["verification_url"] = signing.verification_url(last_log.verification_code)
        del last_log["verification_code"]

    return {"print_formats": contexts, "last_log": last_log,
            "handwritten": {
                "capitalize": bool(signing.settings().handwritten_capitalize),
                "bold": bool(signing.settings().handwritten_bold),
            }}


@frappe.whitelist()
def start(doctype: str, name: str, print_format: str, certificate: str) -> dict:
    return signing.token_start(doctype, name, print_format, certificate)


@frappe.whitelist()
def complete(session_id: str, signature: str) -> dict:
    return signing.token_complete(session_id, signature)


@frappe.whitelist()
def start_batch(items, certificate: str) -> dict:
    """items: [{doctype, name, print_format}]. One token session server-side
    per document; the browser signs every hash with a single PIN prompt."""
    items = _parse_items(items)
    sessions = [
        {**signing.token_start(i["doctype"], i["name"], i["print_format"], certificate),
         "name": i["name"]}
        for i in items
    ]
    return {"sessions": sessions,
            "digest_algorithm": sessions[0]["digest_algorithm"] if sessions else "sha256"}


@frappe.whitelist()
def complete_batch(items) -> dict:
    """items: [{session_id, signature, name}]. Fail-fast like the reference
    server: completed documents stay completed; the error names the failure."""
    items = _parse_items(items, keys=("session_id", "signature"))
    results = []
    for index, item in enumerate(items):
        try:
            results.append({**signing.token_complete(item["session_id"], item["signature"]),
                            "name": item.get("name")})
        except Exception:
            frappe.throw(_("Batch failed at document {0} of {1} ({2}); earlier documents are signed").format(
                index + 1, len(items), item.get("name") or item["session_id"]))
    return {"documents": results}


@frappe.whitelist()
def sign_now(doctype: str, name: str, print_format: str) -> dict:
    """Manual server-key signing from the form button."""
    return signing.server_sign(doctype, name, print_format)


@frappe.whitelist(allow_guest=True)
def download_ecopy(code: str):
    """The QR target's download: the signed e-copy, by capability code."""
    log = _log_by_code(code)
    file_doc = frappe.get_doc("File", {"file_url": log.signed_file})
    frappe.local.response.filename = file_doc.file_name
    frappe.local.response.filecontent = file_doc.get_content()
    frappe.local.response.type = "download"


def _log_by_code(code: str):
    if not code or len(code) < 16:
        frappe.throw(_("Invalid verification code"), frappe.PermissionError)
    name = frappe.db.get_value("Signature Log", {"verification_code": code})
    if not name:
        frappe.throw(_("Unknown verification code"), frappe.DoesNotExistError)
    return frappe.get_doc("Signature Log", name)


def _parse_items(items, keys=("doctype", "name", "print_format")):
    if isinstance(items, str):
        items = json.loads(items)
    if not isinstance(items, list) or not items:
        frappe.throw(_("items must be a non-empty list"))
    if len(items) > signing.BATCH_CAP:
        frappe.throw(_("Batch size is capped at {0} documents").format(signing.BATCH_CAP))
    for item in items:
        if not all(item.get(k) for k in keys):
            frappe.throw(_("Each item needs {0}").format(", ".join(keys)))
    return items
