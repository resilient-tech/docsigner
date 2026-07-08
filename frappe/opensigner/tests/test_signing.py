"""Wrong-input tests for the signing gates and session plumbing.

Run on a bench: bench --site <site> run-tests --app opensigner
Each test asserts what SHOULD happen — a rejection with the right message —
never what happens to happen.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from opensigner import api, signing


def _print_format(**overrides):
    values = {
        "doctype": "Print Format",
        "name": "OpenSigner Test PF",
        "doc_type": "ToDo",
        "print_format_type": "Jinja",
        "html": "<p>{{ doc.name }}</p>",
        "opensigner_enabled": 1,
        "opensigner_style": "Handwritten",
        "opensigner_position": "Bottom Right",
        "opensigner_page": 1,
    }
    values.update(overrides)
    frappe.delete_doc("Print Format", values["name"], force=True, ignore_missing=True)
    return frappe.get_doc(values).insert(ignore_permissions=True)


class TestSigningGates(FrappeTestCase):
    def setUp(self):
        self.todo = frappe.get_doc({"doctype": "ToDo", "description": "sign me"}).insert()

    def test_disabled_print_format_is_rejected(self):
        pf = _print_format(opensigner_enabled=0)
        self.assertRaisesRegex(
            frappe.ValidationError, "not enabled",
            signing.assert_can_sign, self.todo, pf,
        )

    def test_wrong_doctype_print_format_is_rejected(self):
        pf = _print_format(doc_type="Note")
        self.assertRaisesRegex(
            frappe.ValidationError, "does not apply",
            signing.assert_can_sign, self.todo, pf,
        )

    def test_role_gate_rejects_user_without_role(self):
        pf = _print_format(opensigner_signer_role="System Manager")
        original_get_roles = frappe.get_roles
        frappe.get_roles = lambda *a, **k: ["All"]
        try:
            self.assertRaises(
                frappe.PermissionError, signing.assert_can_sign, self.todo, pf
            )
        finally:
            frappe.get_roles = original_get_roles

    def test_unsubmitted_submittable_doc_is_rejected(self):
        pf = _print_format(doc_type="Task")
        task = frappe.new_doc("Task") if frappe.db.exists("DocType", "Task") else None
        if task is None:
            self.skipTest("no submittable test doctype on this site")
        # Monkey-level check: is_submittable drives the gate.
        task.meta.is_submittable = 1
        task.docstatus = 0
        task.doctype = "Task"
        self.assertRaisesRegex(
            frappe.ValidationError, "Submit the document",
            signing.assert_can_sign, task, pf,
        )

    def test_custom_box_must_be_four_points(self):
        pf = _print_format(opensigner_position="Custom Box", opensigner_box="not json")
        self.assertRaisesRegex(
            frappe.ValidationError, "x1, y1, x2, y2",
            signing._appearance, pf, None,
        )

    def test_image_style_without_image_is_rejected(self):
        pf = _print_format(opensigner_style="Image")
        self.assertRaisesRegex(
            frappe.ValidationError, "no Signature Image",
            signing._appearance, pf, None,
        )


class TestSessionsAndBatch(FrappeTestCase):
    def test_unknown_session_is_rejected(self):
        self.assertRaisesRegex(
            frappe.ValidationError, "expired or already used",
            signing.token_complete, "no-such-session", "c2ln",
        )

    def test_foreign_users_session_is_rejected(self):
        frappe.cache().set_value(
            signing._CACHE_PREFIX + "someone-elses",
            json.dumps({"user": "other@example.com", "state": "", "doctype": "ToDo",
                        "name": "x", "print_format": "y", "code": None}),
            expires_in_sec=60,
        )
        self.assertRaises(
            frappe.PermissionError,
            signing.token_complete, "someone-elses", "c2ln",
        )

    def test_batch_cap_is_enforced(self):
        items = [{"doctype": "ToDo", "name": f"T{i}", "print_format": "P"} for i in range(51)]
        self.assertRaisesRegex(
            frappe.ValidationError, "capped at 50",
            api.start_batch, json.dumps(items), "AAAA",
        )

    def test_batch_rejects_incomplete_items(self):
        self.assertRaisesRegex(
            frappe.ValidationError, "Each item needs",
            api.start_batch, json.dumps([{"doctype": "ToDo"}]), "AAAA",
        )

    def test_bad_certificate_encoding_is_rejected(self):
        todo = frappe.get_doc({"doctype": "ToDo", "description": "x"}).insert()
        pf = _print_format()
        self.assertRaisesRegex(
            frappe.ValidationError, "base64",
            signing.token_start, "ToDo", todo.name, pf.name, "!!not-base64!!",
        )


class TestVerifyPage(FrappeTestCase):
    def test_short_code_is_rejected(self):
        self.assertRaises(frappe.PermissionError, api._log_by_code, "short")

    def test_unknown_code_is_rejected(self):
        self.assertRaises(
            frappe.DoesNotExistError, api._log_by_code, "x" * 24,
        )
