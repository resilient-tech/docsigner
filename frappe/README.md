# OpenSigner for Frappe

Digitally sign any doctype's print format PDF, straight from the desk. Signing
happens with a DSC USB token in the user's machine (via the OpenSigner browser
extension + native host) or with a server-held `.p12` key — same stamp, same
evidence, same one flow underneath.

The signed PDF gets a modern, subtle stamp: the signer's name drawn in a
handwriting script, detail lines underneath, and (optionally) a QR code.
Scanning the QR on a **printout** opens a verification page serving the
digitally signed e-copy — paper stays printer-friendly, the signature stays
cryptographic.

## Install

```bash
# 1. signer-core into the bench env (until it's on PyPI)
~/frappe-bench/env/bin/pip install -e /path/to/document-signer/core

# 2. the app
bench get-app /path/to/document-signer/frappe
bench --site yoursite install-app opensigner
```

Token signing additionally needs, on each signer's machine: the OpenSigner
browser extension and the `opensigner-host` native app (see the repo root
README). Server-key signing and auto-sign need neither.

## Configure

**OpenSigner Settings** (single):

- *Default Signature Profile* (default `CCA-LTV`), *Timestamp Authority* /
  *Custom TSA URL*, *Trust Anchor Directory* — profile requirements match the
  core library: timestamped profiles need a TSA, LTV profiles need trust
  anchors (the repo ships a `trust/` folder).
- *PKCS#12 Key File* + *PKCS#12 Password* — the server-held key. Must be a
  private file; the settings refuse a public one.
- *Verification Base URL* — printed inside QR codes; blank uses the site URL.
- *Capitalize Signer Name* / *Bold Signer Name* — handwritten stamp defaults.

**Per print format** (custom fields on Print Format, section "Digital
Signature"): *Enable Digital Signature*, *Sign Mode* (`Token (user signs)` /
`Server Key (automatic)`), *Auto Sign on Submit*, *Signer Role*, *Signature
Profile*, *Stamp Style* (`Handwritten` / `Image` / `Invisible`), *Signature
Image*, *Stamp Position* (corners or *Custom Box* `[x1, y1, x2, y2]` in PDF
points), *Stamp Page*, *QR Verification Link*.

Enabling *Auto Sign on Submit* on a new doctype registers its hook on the
next `bench restart` (hooks are computed per doctype — no wildcard listener).

## Use

- **Form**: submitted documents of an enabled doctype show a **Digitally
  Sign** button. Token mode opens the certificate dialog (last-used
  certificate preselected, stamp preview in the actual script font), the
  token prompts for its PIN, and the signed PDF lands as a private attachment
  with a timeline comment. Server Key mode signs after one confirmation.
- **Bulk**: select up to 50 documents in the list view → *Actions* →
  **Digitally Sign**. One PIN signs the whole batch.
- **Auto**: with *Auto Sign on Submit*, submission enqueues a background
  signature; failures land in the Error Log.
- **Verify**: every QR-stamped document resolves at
  `/os_verify?code=…` — fresh validation verdict plus the e-copy download,
  no login needed (the code is the capability).

Evidence lives in **Signature Log** (append-only: certificate, profile,
SHA-256, audit JSON, signed file). Signed PDFs referenced by a log can only
be deleted by a System Manager.

## Tests

```bash
bench --site yoursite run-tests --app opensigner
```

Live-test checklist for releases: `../plan/live-test-checklist.md`.
