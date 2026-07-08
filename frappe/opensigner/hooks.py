app_name = "opensigner"
app_title = "OpenSigner"
app_publisher = "Resilient Tech"
app_description = (
    "Digitally sign print format PDFs with a DSC token (browser extension + "
    "native host) or a server-held key. PAdES/CCA profiles via signer-core."
)
app_email = "smit@resilient.tech"
app_license = "MIT"

app_include_js = [
    "/assets/opensigner/js/opensigner.iife.js",
    "/assets/opensigner/js/sign.js",
]
app_include_css = ["/assets/opensigner/css/opensigner.css"]

after_install = "opensigner.install.after_install"
after_migrate = "opensigner.install.after_install"

extend_bootinfo = "opensigner.boot.extend_bootinfo"


def _auto_sign_doctypes():
    """Doctypes with an auto-sign print format. Registering only these keeps
    the hook off every other save (no wildcard); a bench restart picks up
    print formats enabled later. Safe during install: the custom column may
    not exist yet."""
    try:
        import frappe

        return frappe.get_all(
            "Print Format",
            filters={"opensigner_enabled": 1, "opensigner_auto_sign": 1},
            distinct=True,
            pluck="doc_type",
        )
    except Exception:
        return []


doc_events = {
    dt: {"on_submit": "opensigner.events.auto_sign_on_submit"}
    for dt in _auto_sign_doctypes()
    if dt
}
doc_events.setdefault("File", {})["before_delete"] = "opensigner.events.protect_signed_file"
