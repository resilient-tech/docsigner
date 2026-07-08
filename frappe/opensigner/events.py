"""Document event handlers wired in hooks.py."""

import frappe
from frappe import _


def auto_sign_on_submit(doc, method=None):
    """Enqueue a server-key signature for every auto-sign print format of this
    doctype. Enqueued after commit so a rolled-back submit signs nothing."""
    for pf in frappe.get_all(
        "Print Format",
        filters={"doc_type": doc.doctype, "opensigner_enabled": 1, "opensigner_auto_sign": 1},
        pluck="name",
    ):
        frappe.enqueue(
            "opensigner.signing.server_sign_job",
            doctype=doc.doctype, name=doc.name, print_format=pf,
            queue="long", enqueue_after_commit=True,
        )


def protect_signed_file(doc, method=None):
    """Refuse deleting a signed PDF unless a System Manager does it — that
    file is signing evidence referenced by a Signature Log."""
    if not doc.file_url:
        return
    if not frappe.db.exists("Signature Log", {"signed_file": doc.file_url}):
        return
    if "System Manager" not in frappe.get_roles():
        frappe.throw(
            _("This file is a digitally signed PDF referenced by a Signature Log; only a System Manager may delete it"),
            frappe.PermissionError,
        )
