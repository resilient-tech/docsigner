"""The QR target: anyone scanning a stamped printout lands here and gets the
digitally signed e-copy plus a fresh validation verdict (another vendor's
printer-friendly pattern). The verification code is the capability."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
    context.no_breadcrumbs = True
    code = frappe.form_dict.get("code") or ""
    context.found = False
    if not code or len(code) < 16:
        return context

    name = frappe.db.get_value("Signature Log", {"verification_code": code})
    if not name:
        return context

    log = frappe.get_doc("Signature Log", name)
    context.found = True
    context.log = log
    context.download_url = (
        f"/api/method/opensigner.api.download_ecopy?code={frappe.utils.quote(code)}"
    )

    # Fresh verdict on the stored bytes, not a replay of the stored audit.
    try:
        from signer_core import validate

        from opensigner.signing import settings

        content = frappe.get_doc("File", {"file_url": log.signed_file}).get_content()
        if isinstance(content, str):
            content = content.encode("latin-1")
        results = validate(content, settings().trust_dir or None)
        match = [r for r in results if r.get("field_name") == log.field_name] or results
        context.verdict = match[0] if match else None
        context.trust_checked = bool(settings().trust_dir)
    except Exception:
        frappe.log_error(title=f"os_verify failed for Signature Log {log.name}")
        context.verdict = None
        context.trust_checked = False
    return context
