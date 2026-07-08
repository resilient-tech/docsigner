import frappe


def extend_bootinfo(bootinfo):
    """Doctypes with signing-enabled print formats, so sign.js knows where to
    show buttons without a call per form. Safe pre-migrate."""
    try:
        bootinfo.opensigner = {
            "doctypes": frappe.get_all(
                "Print Format",
                filters={"opensigner_enabled": 1},
                distinct=True,
                pluck="doc_type",
            )
        }
    except Exception:
        bootinfo.opensigner = {"doctypes": []}
