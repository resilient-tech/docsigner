from frappe.model.document import Document


class SignatureLog(Document):
    """Append-only signing evidence. in_create + read-only permissions keep it
    immutable from the desk; inserts happen server-side in signing.finalize."""
