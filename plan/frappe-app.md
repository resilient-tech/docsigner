# Frappe App Plan: `docsigner_integration`

Branch: `develop`. One commit per milestone. Status column updated as work lands — this file is where the next session looks.

**2026-07-08 — moved and renamed.** The app now lives in its own repo
(`apps/docsigner_integration` on the bench, branch `develop`), python package
`docsigner_integration`, module `Docsigner Integration`, license AGPL-3.0
(from the bench scaffold), `use_json_request_body` on. Everything else below
still describes the shipped design; read `frappe/` paths as the app repo, and
dotted paths as `docsigner_integration.*`. Unchanged on purpose: the
`docsigner_` custom-field prefix, the `docsigner:session:` cache prefix, the
`bootinfo.docsigner` key, and the `/os_verify` route — they name the product,
not the package.

## Goal

A Frappe app that signs any doctype's print format PDF with a DSC token (browser extension + native host) or a server-held key. Handwritten-style visible stamp by default, QR on the stamp that resolves to a digitally signed e-copy. Config lives on Print Format via custom fields. One signing flow, every entry point routes through it.

## Decisions (settled here, not re-litigated)

| # | Decision | Why |
|---|----------|-----|
| D1 | Fresh app `docsigner`, publisher Resilient Tech. Built on our own stack, not adapted from an existing Frappe signing app. | The alternatives ship a parallel signing ceremony (a bridge agent, pairing, HMAC). We already have extension + host + signer-core. One flow, one implementation. |
| D2 | signer-core embedded as pip dep. No FastAPI server in the bench. | Same Python process, no second service. The FastAPI server remains the non-Frappe reference. |
| D3 | Signing sessions in `frappe.cache()` (redis), `SessionState.to_bytes()`, 15 min TTL, pop-on-read. | Survives worker restarts; no files inside bench. |
| D4 | Per-print-format config = custom fields on Print Format (`docsigner_` prefix). No Rule/Template doctypes in v1. | Config lives where the document layout lives. Fewer doctypes. |
| D5 | Per-user default certificate = browser localStorage (last-used thumbprint auto-preselected). No server-side mapping. | The token is plugged into a machine, not a site. Right scope, zero config. |
| D6 | Handwritten stamp + QR composed server-side into one PNG (PIL) in signer-core; passed through the existing `background` path. | One renderer for name/details/QR/image; no new pyHanko surface; testable with PIL alone. |
| D7 | Verify page is a capability URL: `/os_verify?code=<22+ char secret>`. Guest download allowed by code only. | Printer-friendly verify pattern. Code strength is the access control. |
| D8 | Signature Log is append-only evidence (audit JSON from core), protected signed Files (`before_delete` guard). | Evidence survives; deleting a signed PDF is a data-loss path. |
| D9 | Batch cap 50, session TTL 15 min: constants, not settings. | Safety rules are constants, not judgment calls. |
| D10 | Sign requires: doc submitted (if submittable), `print` permission on the doc, optional Role gate from Print Format. | Reuse platform permissions before inventing new ones. |
| D11 | App license MIT (placeholder until repo-wide license is picked — README lists that as a pre-release task). | hooks.py needs a string today. |
| D12 | CONTRACTS.md gets a Changelog section; appearance additions are additive, REST-only → `protocolVersion` stays 1. | Additive by default; version-gate only breaking changes. |
| D13 | Ten bundled OFL handwriting fonts, picked in Settings (`appearance.font`); preview in the cert dialog uses the same woff2. | One renderer, fonts are data. |
| D14 | Trust anchors ship inside the Frappe app (`docsigner_integration/trust/`, 176 KB); blank Trust Anchor Directory = bundled. Refresh path: rerun `scripts/fetch_trust_roots.py` in the core repo and copy over. | Users don't understand trust dirs; signing and verification must work out of the box. |
| D15 | Token PINs are never **stored**: not in Settings, not in localStorage, never sent to the Frappe server. Amended 2026-07-10: the sign dialog may collect the PIN per signing session (that is the authorisation moment) and pass it browser-side to the host via CONTRACTS §2 page-supplied `pin`; it lives in JS memory for the run and is cleared when the dialog closes. Blank field = host prompts natively, as before. | A stored PIN turns "something you have + know" into "something the DB has". Entry at sign time is authorisation; storage is the vulnerability. Per-session entry is what lets a chunked batch run unattended (plan/next-phases.md Phase 7.5). |
| D16 | Signing config on **custom** print formats is the recommended path for developer-mode benches; standard print formats' exported JSONs pick up `docsigner_*` values on save (frappe exports the whole doc). | Known frappe dev-mode behaviour; upstream fix = export should skip custom fields (contribution candidate). |

## Architecture

```
Desk form/list ── sign.js ──► DocSigner extension ──► host ──► token
      │                                                (PIN, signature)
      ▼
docsigner.api (whitelisted) ──► docsigner.signing (THE wrapper)
      │                                │
frappe.get_print → PDF          signer-core (SigningSession / sign_with_p12)
      │                                │
      ▼                                ▼
File attach + Signature Log + timeline comment + QR → /os_verify
```

## Milestones

| M | Scope | Files (exclusive lanes) | Status |
|---|-------|-------------------------|--------|
| M0 | develop branch, this plan | `plan/` | ✅ done |
| M1 | core: `style:"handwritten"`, `qr_url`, bundled fonts, `qrcode` dep, tests, CONTRACTS changelog | `core/signer_core/appearance.py`, `core/signer_core/fonts/`, `core/tests/test_appearance.py`, `core/pyproject.toml`, `CONTRACTS.md` | ✅ done |
| M2 | app scaffold: pyproject, hooks (correct title/publisher), modules, install (custom fields on Print Format, install+migrate) | `frappe/` | ✅ done |
| M3 | DocSigner Settings (Single) + Signature Log doctypes | `frappe/docsigner/docsigner/doctype/` | ✅ done |
| M4 | `signing.py` wrapper + `api.py` (get_sign_context, start, complete, start_batch, complete_batch, sign_server_side) | `frappe/docsigner/signing.py`, `api.py`, `boot.py` | ✅ done |
| M5 | JS: form button, cert dialog (remembered cert, handwritten preview, error map), bulk list action | `frappe/docsigner/public/js/` | ✅ done |
| M6 | auto-sign on_submit (dynamic doc_events), File delete guard | `hooks.py`, `frappe/docsigner/events.py` | ✅ done |
| M7 | `/os_verify` guest page + download-by-code | `frappe/docsigner/www/` | ✅ done |
| M8 | core pytest run, py-compile pass, app README (from code), live-test checklist | `frappe/README.md`, `plan/live-test-checklist.md` | ✅ done |

## Workflows (all through `signing.py`)

1. **Manual token sign** — form button → cert dialog → `start` → extension `signHash` → `complete` → File + Log + comment.
2. **Bulk token sign** — list checkboxes → `start_batch` (≤50) → ONE `signHash`, one PIN → `complete_batch` → summary.
3. **Auto server sign** — `on_submit` (only doctypes with an auto-sign print format registered) → enqueue → `sign_server_side`.
4. **Manual server sign** — same button when mode = Server Key; no extension needed.
5. **Verify/e-copy** — QR on stamp → `/os_verify?code=…` → re-validate via signer-core → validity + signed PDF download.

Common ceremony (never duplicated): `prepare(doc, pf)` → PDF + appearance + verification code; `finalize(pdf, …)` → File + Log + comment. Token and server paths differ only in the middle step.

## Print Format custom fields

`docsigner_section` (collapsible) · `docsigner_enabled` (Check) · `docsigner_mode` (Token / Server Key) · `docsigner_auto_sign` (Check, Server Key only) · `docsigner_style` (Handwritten / Image / Invisible) · `docsigner_signature_image` (Attach, Image style) · `docsigner_position` (4 corners / Custom Box) · `docsigner_box` (Data, PDF points) · `docsigner_page` (Int, 1-based) · `docsigner_qr` (Check) · `docsigner_profile` (Select, blank = Settings default) · `docsigner_signer_role` (Link Role)

## DocSigner Settings (Single)

default_profile (CCA-LTV) · tsa (registry name) · trust_dir · p12_file (private Attach) + p12_password (Password) · verify_base_url (blank = site URL) · handwritten_capitalize (default on) · handwritten_bold (default off)

## Signature Log

ref_doctype, ref_name (dynamic link), print_format, signer, certificate_subject/serial/issuer, profile, digest_algorithm, document_sha256, field_name, signed_file, verification_code (unique), audit_json. Insert-only.

## Standards applied (from bankbridge learnings)

- Every button ships with a live-test line in `plan/live-test-checklist.md`; a human runs it before any tag.
- Wrong-input tests: bad session id, expired session, wrong signature bytes, unauthorised role, unsubmitted doc.
- Docs (app README) written from code — field labels and button names copied from source, same commit as behaviour.
- Interface changes: CONTRACTS.md changelog entry lands in the same commit (M1).
- Constants: batch cap 50, TTL 900 s — named constants at top of `signing.py`.
- Root fixes: permission + docstatus gates live in `signing.py` prepare, not per caller.

## Skipped on purpose (add when a real user asks)

Rule-engine conditions, print/email gating of unsigned docs, geolocation evidence, signature placement drag-UI, workflow-state triggers, Aadhaar eSign, per-user server-side cert mapping.

## Future candidates (noted 2026-07-08, from live testing)

Planned in detail with milestones in `plan/next-phases.md` (phases 6 to 10).

- **Sign arbitrary attachments**: a demo-like tool in the desk — pick any File attachment (or upload a PDF), sign it with token or server key, replace/attach alongside (upload + drag placement). Reuses the whole ceremony; new surface only.
- **Marks on all pages**: a visible watermark stamp on every page plus the one cryptographic signature field. Needs a non-signature stamp pass in core.
- **Frappe contribution**: standard-doc export in developer mode writes custom field values into the app's JSON; upstream fix is to strip non-standard fields in export_to_files.
