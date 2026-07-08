"""Custom fields on Print Format — the per-print-format signature config.

Runs on install and on every migrate; create_custom_fields is idempotent.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

PROFILES = "\nB-B\nB-T\nB-LT\nB-LTA\nCCA-LTV\nCCA-LTA"

PRINT_FORMAT_FIELDS = {
    "Print Format": [
        {
            "fieldname": "opensigner_section",
            "fieldtype": "Section Break",
            "label": "Digital Signature",
            "collapsible": 1,
        },
        {
            "fieldname": "opensigner_enabled",
            "fieldtype": "Check",
            "label": "Enable Digital Signature",
        },
        {
            "fieldname": "opensigner_mode",
            "fieldtype": "Select",
            "label": "Sign Mode",
            "options": "Token (user signs)\nServer Key (automatic)",
            "default": "Token (user signs)",
            "depends_on": "eval:doc.opensigner_enabled",
        },
        {
            "fieldname": "opensigner_auto_sign",
            "fieldtype": "Check",
            "label": "Auto Sign on Submit",
            "depends_on": (
                "eval:doc.opensigner_enabled && "
                "doc.opensigner_mode == 'Server Key (automatic)'"
            ),
            "description": "Sign in the background whenever a document is submitted",
        },
        {
            "fieldname": "opensigner_signer_role",
            "fieldtype": "Link",
            "label": "Signer Role",
            "options": "Role",
            "depends_on": "eval:doc.opensigner_enabled",
            "description": "Only users with this role may sign; blank allows anyone with print permission",
        },
        {
            "fieldname": "opensigner_profile",
            "fieldtype": "Select",
            "label": "Signature Profile",
            "options": PROFILES,
            "depends_on": "eval:doc.opensigner_enabled",
            "description": "Blank uses the default from OpenSigner Settings",
        },
        {"fieldname": "opensigner_column", "fieldtype": "Column Break"},
        {
            "fieldname": "opensigner_style",
            "fieldtype": "Select",
            "label": "Stamp Style",
            "options": "Handwritten\nImage\nInvisible",
            "default": "Handwritten",
            "depends_on": "eval:doc.opensigner_enabled",
        },
        {
            "fieldname": "opensigner_signature_image",
            "fieldtype": "Attach Image",
            "label": "Signature Image",
            "depends_on": (
                "eval:doc.opensigner_enabled && doc.opensigner_style == 'Image'"
            ),
        },
        {
            "fieldname": "opensigner_position",
            "fieldtype": "Select",
            "label": "Stamp Position",
            "options": "Bottom Right\nBottom Left\nTop Right\nTop Left\nCustom Box",
            "default": "Bottom Right",
            "depends_on": (
                "eval:doc.opensigner_enabled && doc.opensigner_style != 'Invisible'"
            ),
        },
        {
            "fieldname": "opensigner_box",
            "fieldtype": "Data",
            "label": "Custom Box",
            "depends_on": (
                "eval:doc.opensigner_enabled && doc.opensigner_position == 'Custom Box'"
            ),
            "description": "[x1, y1, x2, y2] in PDF points, origin bottom-left",
        },
        {
            "fieldname": "opensigner_page",
            "fieldtype": "Int",
            "label": "Stamp Page",
            "default": "1",
            "depends_on": (
                "eval:doc.opensigner_enabled && doc.opensigner_style != 'Invisible'"
            ),
            "description": "1-based page number carrying the stamp",
        },
        {
            "fieldname": "opensigner_qr",
            "fieldtype": "Check",
            "label": "QR Verification Link",
            "depends_on": (
                "eval:doc.opensigner_enabled && doc.opensigner_style != 'Invisible'"
            ),
            "description": "Stamp carries a QR; scanning it opens a page serving the signed e-copy",
        },
    ]
}


def after_install():
    create_custom_fields(PRINT_FORMAT_FIELDS, ignore_validate=True)
