import frappe
from frappe.model.document import Document


class OpenSignerSettings(Document):
    def validate(self):
        if self.p12_file and not self.p12_file.startswith("/private/"):
            frappe.throw(
                "The PKCS#12 key file must be a private file — re-upload with "
                '"Private" checked; a public key file would be downloadable by anyone.'
            )
