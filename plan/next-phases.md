# Next phases: device-layer reliability, desk polish, distribution

Written 2026-07-08, after the first live week on a real bench with a real Capricorn token. PLAN.md phases 0 to 5 built the stack; this file plans what comes after. Same rules as plan/frappe-app.md: one commit per milestone, status column updated as work lands, exclusive file lanes per milestone.

Repos: `document-signer` (core, host, extension, js, server) and `apps/docsigner_integration` (the Frappe app). Milestones say which repo they touch.

## What live testing taught us (2026-07-08)

- Certificate listing fails intermittently and the UI couldn't say why. The page library was dropping the host's `readers` array, so every empty list showed the same generic "plug in your token" hint. Fixed: `listCertificates()` now returns `{certificates, readers, diagnostics}`, the host reports per-source scan counters, and the desk dialog picks the hint that matches the counters.
- The remaining empty-list suspects are environmental: the single-session lock in ePass/ProxKey drivers (a vendor utility, a second browser profile's host process, or a third-party signing host holding the token), and drivers that only enumerate at C_Initialize. `lib.reinitialize()` per scan covers the second; the first needs detection, which is Phase 6.
- SHA-512 works end to end. Verified by parsing the CMS of the live signed PDFs: digest, signature algorithm, messageDigest and TSA imprint all sha512. The confusion was display: the verify page labelled the file fingerprint "SHA-256" and never showed the signature digest. Fixed on the verify page; the server-key audit record also recorded sha256 unconditionally, fixed in signing.py.
- Ten handwriting fonts was too many and some woff2 faces weren't loading in the desk. Trimmed to one per personality: great-vibes (calligraphy), caveat (casual), nanum-pen-script (pen), cookie (brush), bad-script (neat script). Migrate patch resets stale settings values.
- Capitalize did nothing visible because DSC CNs already arrive in caps. It now title-cases: RAHUL SHARMA renders as Rahul Sharma. Core, dialog preview and settings preview share the rule.
- Print Format custom fields from other apps were landing inside our Digital Signature section. A closing Section Break after `docsigner_qr` fixes it.

## Phase 6: device-layer reliability (host + extension)

The goal: an empty certificate list is always explainable and usually self-healing. Everything here is `document-signer` repo.

| M | Scope | Files | Status |
|---|-------|-------|--------|
| M6.1 | Diagnostics pipeline: host scan counters in the listCertificates result, js pass-through, desk hints keyed on counters, CONTRACTS §2/§4 | `host/signer_host/protocol.py`, `pkcs11_ops.py`, `js/docsigner.js`, `CONTRACTS.md`, app `sign.js` | ✅ done (2026-07-08) |
| M6.2 | Scan watchdog: run each PKCS#11 module scan on a worker thread with a 20 s budget; a stuck driver yields a diagnostics entry naming the module instead of a 120 s browser timeout. Slow modules logged with timings. | `host/signer_host/pkcs11_ops.py`, `host/tests/` | ✅ done (2026-07-08) |
| M6.3 | Competing-process detection: at scan time, list other `docsigner-host` processes and known token-vendor utilities (platform `ps`/`tasklist` parse, no new deps); surface as `diagnostics.competingProcesses` so the desk hint can name the actual culprit. | `host/signer_host/` (new `procs.py`), `protocol.py`, app `sign.js` | ✅ done (2026-07-08) |
| M6.4 | Support bundle: "Copy diagnostics" button in the no-certificates dialog (counters + readers + host version); `getVersion` gains the host.log path so support asks for one file. | app `sign.js`, `host/signer_host/protocol.py`, CONTRACTS changelog | ✅ done (2026-07-08) |
| M6.5 | Live checklist additions: replug during dialog, two browsers at once, vendor utility running, WebPKI installed alongside. Each with the expected hint text. | `plan/live-test-checklist.md` | ✅ done (2026-07-08) |

Exit: on a machine where listing fails, the dialog names the cause (driver missing, driver stuck, token held by process X, token absent) and the copyable diagnostics match the host log.

## Phase 7: desk UX finish (Frappe app)

| M | Scope | Files | Status |
|---|-------|-------|--------|
| M7.1 | Verify page layout: long DNs and hashes wrap inside the card; signature digest shown; file fingerprint labelled as such. | `www/os_verify.html`, `signing.py` | ✅ done (2026-07-08) |
| M7.2 | Verify page readability: CN as the headline "Signed by", full RFC4514 subject behind a details toggle, serial number row, mobile pass (QR scans happen on phones). | `www/os_verify.html`, `www/os_verify.py` | ✅ done (2026-07-10) |
| M7.3 | Certificate dialog: show all five font personalities as clickable samples when picking a font in Settings, so the choice is visual instead of a slug dropdown. | `docsigner_settings.js`, `docsigner.css` | ✅ done (2026-07-10) |
| M7.4 | Signature Log list view: status indicator (verified at signing), quick links to file and verify page; log row links back from the timeline comment. | `signature_log.json`, list JS | ✅ done (2026-07-10) |
| M7.5 | Wrong-input tests for the new hint logic and the patch (stale font value, batch with mixed print formats). | `tests/test_signing.py` | ✅ done (2026-07-10) |

Exit: a phone scan of a stamped printout reads cleanly, and a System Manager can audit a month of signatures from the Signature Log list without opening rows.

## Phase 7.5: signing dialog and bulk ergonomics (Frappe app)

Live feedback (2026-07-10): too many hops before the PIN prompt, and a 50-doc batch renders and holds every PDF at once. Design call on the PIN: the dialog collects it per signing session, because that is the authorisation moment; the vulnerability is storage, not entry. The PIN travels browser → extension → host only (CONTRACTS §2 page-supplied `pin`), never reaches the Frappe server, localStorage or Settings, and is cleared when the dialog closes. This is what makes the one-go UX work: the user fills everything once and a chunked batch runs unattended, no host prompt landing minutes later. D15 amended in plan/frappe-app.md. Token bulk stays browser-driven by design: the token is on the user's machine, every hash round-trips the browser, so server-side background signing is a server-key-only feature.

| M | Scope | Files | Status |
|---|-------|-------|--------|
| M7.6 | One sign dialog: print format select (filtered to `docsigner_enabled`), certificate as an Autocomplete (CN as label; issuer, expiry, token label, serial in the description; remembered thumbprint preselected), optional "Reason for signing" text, and a Password-type token PIN field (blank = host prompts natively, as today). Replaces the separate print-format prompt. | `sign.js`, `docsigner.css` | ✅ done (2026-07-10; serial shows once the host sends it — not in the listCertificates result yet) |
| M7.7 | Reason plumbed through: core accepts `reason` into the CMS signature metadata (Adobe shows it), Signature Log stores it, verify page shows it. Additive, CONTRACTS changelog. | `core/signer_core/`, `signing.py`, `signature_log.json`, `www/os_verify.*`, `CONTRACTS.md` | ✅ done (2026-07-10; core already had `options.reason`, app-side plumbing only) |
| M7.8 | Chunked token batch: render, hash, sign, complete in chunks of 10 inside the existing start_batch/complete_batch shape. Dialog PIN passed to each `signHash` client-side, so the run needs no interaction after the dialog; PIN kept in JS memory only, cleared on close. Wrong PIN fails the first chunk with `PIN_INCORRECT` mapped to a re-prompt, later chunks never see a bad PIN. Dialog shows x/50 progress; `beforeunload` warning while a chunk is in flight, removed on completion. | `sign.js`, `signing.py`, `api.py` | ✅ done (2026-07-10) |
| M7.9 | Batch resume: skip docs already signed for that print format (Signature Log lookup), so re-running a broken batch finishes the remainder with no duplicates. Completed chunks are already committed per chunk; a mid-run browser close loses only the in-flight chunk to session TTL. | `signing.py` | ✅ done (2026-07-10) |
| M7.10 | Server-key bulk in background: enqueue, realtime progress, Notification on completion, safe to close the browser. | `signing.py`, `api.py`, `sign.js` | ✅ done (2026-07-10) |

Exit: a 50-doc token batch shows one PIN prompt, flat memory, live progress, and a broken run re-runs cleanly; a server-key batch completes with the browser closed.

## Phase 8: sign attachments in context (Frappe app)

Picked from the future-candidates list because live testing kept wanting it: sign a PDF that is not a print format (scanned agreements, uploaded invoices). Design call (2026-07-10): signing happens on the form where the attachment lives, not on a separate page. The signed copy attaches to the same document, the timeline links it, and sharing reuses the standard email composer. A standalone page exists only as the no-parent-doc fallback.

| M | Scope | Files | Status |
|---|-------|-------|--------|
| M8.1 | `signing.prepare_file()` beside `prepare()`: same gates minus print permission (File read instead), same appearance and profile options from Settings. `finalize()` attaches the signed copy to the source File's parent doc as `<name> (signed).pdf`, original kept; timeline comment links original, signed copy and verify URL. | `signing.py`, `api.py` | ✅ done (2026-07-10) |
| M8.2 | Form entry point: Sign button menu gains "Sign attachment…" → picker dialog listing the doc's PDF attachments plus upload → existing certificate dialog. `sign.js` refactored into a shared module so print-format and file paths run the same ceremony UI. | `sign.js` refactor into shared module | ✅ done (2026-07-10; `docsigner.sign_file` is the shared surface) |
| M8.3 | Optional stamp placement: click a spot on a rendered page preview to set the box (a click, not a drag). | shared module JS | ✅ done (2026-07-10; server renders the page via pypdfium2, new app dependency) |
| M8.4 | Signature Log grows `source_file`; verify page unchanged (same capability code path). | `signature_log.json`, `signing.py` | ✅ done (2026-07-10) |
| M8.5 | Share from the success state: "Email signed copy" opens the standard Communication composer with the signed File pre-attached, recipient prefilled from the doc's contact, verify link in the body. "Copy verify link" beside it. No new email surface. | shared module JS | ✅ done (2026-07-10) |
| M8.6 | Fallback desk page "Sign a PDF" for ad-hoc uploads with no parent doc: thin wrapper over the shared module; signed copy and Log attach to the File itself. | new `page/` | ✅ done (2026-07-10) |
| M8.7 | Multi-attachment signing: the dialog's file picker is a MultiCheck (all PDFs, checked by default); N start_file calls, one signHash (one PIN for all), N completes, fail-fast. Click placement applies to the file it was placed on, others default. Success state emails all copies in one composer, copies all verify links. No server change. | `sign.js` | ✅ done (2026-07-10) |
| M8.8 | Attach-dialog stamp options, print-format style: collapsible section with Position (4 corners) and Page (first/last) presets, QR on/off (verify code still issued), MultiCheck select-all buttons + 2 columns. Success secondary is Download copies (verify links already ride the email). | `sign.js`, `signing.py`, `api.py` | ✅ done (2026-07-10) |

Exit: a user signs a PDF attached to a Quotation and emails the signed copy without leaving the form; the e-copy QR verifies like a print format signature.

## Phase 9: multi-page marks and co-signing (core + app)

Co-sign design call (2026-07-10): one signed copy per source file, its content updated in place each round — incremental PDF revisions mean the latest file carries every signature, so a two-signer doc shows one original plus one signed copy, never a pile. Per-round evidence (hashes, audit_json) lives in Signature Log rows. Routing stays native: ToDo + notification for "your turn", Frappe Workflow conditions for enforcement. No envelope doctype, no routing engine.

| M | Scope | Files | Status |
|---|-------|-------|--------|
| M9.1 | Core: watermark pass. A visible mark on every page (name, date, page x of y) plus the one cryptographic field. Non-signature stamps, one incremental revision. | `core/signer_core/appearance.py` (new `marks.py`), tests | ☐ |
| M9.2 | App: "Mark all pages" checkbox on Print Format; marks styled from the same handwritten settings. | `install.py`, `signing.py` | ☐ |
| M9.3 | Co-signing: sign-again on an already-signed attachment. Dialog lists prior signatures (who, when, corner) and preselects a free corner; signed File updated in place, one Signature Log row per round. | shared module JS, `signing.py` | ☐ |
| M9.4 | Validation surface: `/os_verify` lists every signature on the file, not just the logged one. | `www/os_verify.py`, `www/os_verify.html` | ☐ |
| M9.5 | Request next signature: success state gains "Request signature" → pick a user → ToDo assigned to them + notification linking the doc. Signed attachments show a signature-count badge in the picker. | shared module JS, `signing.py` | ☐ |
| M9.6 | `has_signed(doctype, name, user, role=None)` helper (Signature Log lookup), usable in Workflow transition conditions so a state like QC Approved is unreachable until required signers have signed. | `signing.py`, `api.py` | ☐ |

Exit: a QC report signed by the reviewer, routed to the approver via ToDo, co-signed — both signatures valid in Adobe, both on the verify page, and a Workflow gate on `has_signed` holds.

## Phase 9.5: workflow transition signing (core + app)

Frappe Workflow transitions are already the shape of a signing moment: role-gated, named action, one user, one timestamp. Today that approval is a DB row; a signature makes it portable proof on the PDF itself. Design calls (2026-07-10): opt-in per transition, never global (a PIN on every workflow click kills low-stakes workflows). Freeze at first signed transition: the print PDF is rendered and signed once, later flagged transitions co-sign that frozen file, so all signers sign the same bytes. Token mode only for flagged transitions; a server key is an org seal, not a personal approval.

| M | Scope | Files | Status |
|---|-------|-------|--------|
| M9.7 | Core: `caption` line above the name on the stamp ("Reviewed by", "Approved by"). Additive appearance field, CONTRACTS changelog. | `core/signer_core/appearance.py`, tests, `CONTRACTS.md` | ☐ |
| M9.8 | Custom field `docsigner_sign` (Check) on Workflow Transition. `sign.js` intercepts the Actions click on flagged transitions: sign dialog opens with caption = action name, transition applies only after `complete`; cancel or failure leaves the state untouched. | `install.py`, shared module JS, `signing.py` | ☐ |
| M9.9 | Freeze: first flagged transition renders, signs and attaches the print PDF; later flagged transitions co-sign the frozen file (Phase 9 in-place update). Doc modified since freeze → warn; re-freeze voids prior signatures and says so loudly. | `signing.py`, shared module JS | ☐ |
| M9.10 | Evidence and enforcement: Signature Log grows `workflow_action` + `workflow_state`; server refuses a flagged transition without its Log row (UI does the ceremony, API cannot bypass); verify page shows the caption chain. | `signature_log.json`, `signing.py`, `www/os_verify.*` | ☐ |

Exit: a Review → Approve workflow yields one PDF stamped "Reviewed by x" and "Approved by y", both valid in Adobe and on the verify page, and the Approved state is unreachable without both signatures.

## Phase 10: distribution (both repos)

PLAN.md Phase 5, now with what live testing added.

| M | Scope | Files | Status |
|---|-------|-------|--------|
| M10.1 | Extension listings: Chrome Web Store and Firefox AMO. Store copy from README; privacy answers from CONTRACTS (no analytics, no remote calls). | `extension/`, `dist/firefox-extension/` | ☐ |
| M10.2 | Host installers: pkg (notarized), MSI (Authenticode), deb/rpm. Budget the signing certificates first; store review and notarization are the long poles. | `host-rs/packaging/` | ☐ |
| M10.3 | Update channel: wire the host's existing `checkUpdate` into the desk (Settings banner when a newer host is published) and the extension consent page. | `update.py`, app `sign.js` | ☐ |
| M10.4 | Docs: token compatibility table seeded from `modules.py` and `pcsc.py` known lists, integrate-in-10-minutes guide against the reference server, bench install guide for the app. | `docs/` | ☐ |
| M10.5 | Frappe contribution: developer-mode export writes custom field values into standard print format JSONs (D16). Patch upstream `export_to_files` to skip non-standard fields. | frappe fork PR | ☐ |

Exit: a stranger installs extension + host from public listings, installs the app with bench get-app, and signs on the first try.

## Ordering and why

Phase 6 first: reliability of listing is the one thing that erodes trust in the whole product, and M6.2/M6.3 are the two known unexplained failure modes left. Phase 7 rides behind it because most of its surface (dialog, verify page) is already warm from this week's fixes.

Phase 7.5 before 8: Phase 8's shared ceremony module builds on the unified dialog, so the dialog settles first; the chunked batch touches the same start/complete surface Phase 8 reuses.

Phase 8 before 9: arbitrary-attachment signing reuses the existing ceremony and unlocks daily use beyond print formats; multi-page marks need new core surface and can wait for demand to shape them.

Phase 9.5 after 9: transition signing needs co-signing (M9.3) and the multi-signature verify page (M9.4) working first. It closes the loop the QC case opened: "workflow-state triggers" left the skipped-on-purpose list when a real user asked.

Phase 10 last, but M10.2's signing certificates should be ordered during Phase 7. Notarization and store review have multi-week lead times and nothing in phases 6 to 9 depends on them.
