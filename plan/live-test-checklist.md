# Live-test checklist — docsigner Frappe app

Run by a human on a real bench with a real token before any tag. Every button
ships with one real click behind it; no path goes live untouched.

Setup: bench with ERPNext or vanilla Frappe, app installed, a Print Format on
ToDo (or Sales Invoice) with *Enable Digital Signature* checked. A DSC token +
extension + host on the test machine. A test `.p12` uploaded in settings.

## Token flow (form)

- [ ] Enabled doctype, submitted doc → **Digitally Sign** button appears
- [ ] Draft (unsubmitted) doc → button absent; direct API call rejects with "Submit the document before signing it"
- [ ] Click → certificate dialog lists token certs; last-used cert preselected on second run
- [ ] Stamp preview shows the cert CN in script font; capitalize/bold follow settings
- [ ] Sign → native PIN prompt → signed PDF attached (private), timeline comment added, Signature Log row created
- [ ] Signed PDF opens in Adobe Reader with a valid signature panel
- [ ] **Wrong PIN** → "Wrong PIN" message, no log row, no attachment
- [ ] **Dismiss PIN dialog** (USER_CANCELLED) → silent return, nothing created
- [ ] **Token unplugged** after dialog opened → clear TOKEN/MODULE error message
- [ ] Extension disabled → "extension not installed" message with reload hint
- [ ] Second sign on same doc → "Digitally Sign Again", new revision signs on top; both signatures valid in Adobe

## Device-layer diagnostics (Phase 6)

- [ ] Token unplugged, click Sign → "Plug in your DSC token and try again"
- [ ] Token replugged while the cert dialog is open → re-click Sign lists certs again (no browser restart)
- [ ] Vendor utility (or another PKCS#11 host) running, token plugged → hint names the program to close
- [ ] Two browsers with the extension, both list certs → second browser either lists or names "another DocSigner host"
- [ ] Driver wedged (replug during a scan) → within ~20 s the hint says the driver is not responding, not a 2-minute hang
- [ ] Wedged scan (reader present, 0 certs, e.g. ProxKey after sleep) → hint says the connection was reset; second click lists certificates without touching the extension
- [ ] "No certificates found" dialog → Diagnostics expands, Copy diagnostics puts JSON on the clipboard
- [ ] host.log shows the same counters the dialog copied

## Server-key flow

- [ ] Print Format on Server Key mode → button asks for confirmation, signs without extension
- [ ] Settings without p12 → "Upload a PKCS#12 key file" error
- [ ] Public (non-private) p12 upload → settings validation refuses to save

## Bulk

- [ ] Select 3 docs → Actions → Digitally Sign → one PIN → 3 signed PDFs, 3 log rows
- [ ] Select 51 docs → capped-at-50 message, nothing signed
- [ ] Batch where doc 2 is a draft → fail-fast error names the document; doc 1 stays signed (by design)

## One dialog + PIN + batches (Phase 7.5)

- [ ] Sign dialog is one stop: print format, certificate, reason, PIN — no second prompt before signing
- [ ] Certificate dropdown shows CN with issuer/expiry/token label underneath; remembered cert preselected and shows its CN, not a hex thumbprint
- [ ] Blank PIN field → host's native PIN prompt, as before
- [ ] PIN typed in the dialog → no native prompt appears at all
- [ ] Wrong dialog PIN on a single doc → "Wrong PIN" message, no log row
- [ ] Reason typed in the dialog → visible in Adobe's signature panel, Signature Log row and verify page
- [ ] Bulk 25 docs with dialog PIN → chunks of 10, live x/25 progress, zero interaction after the dialog
- [ ] Wrong PIN in bulk → re-prompt dialog, corrected PIN finishes the run, nothing signed twice
- [ ] Close the tab mid-batch → browser warns; re-run the same selection → already-signed skipped ("n already signed and skipped"), no duplicate log rows
- [ ] Server-key bulk → returns immediately ("safe to close this page"), progress streams live, closing the browser mid-run still finishes — Notification in the bell on return
- [ ] Server-key bulk with one draft doc in the selection → fails fast before enqueue (first-doc gate) or lands in the failed count with an Error Log entry

## Attachments (Phase 8)

- [ ] Form → Digitally Sign ▾ shows "Print format…" and "Attachment…"; attachment picker lists only PDF attachments, upload button adds one
- [ ] Sign an attached PDF with the token → `<name> (signed).pdf` attached to the same doc, original kept, timeline comment links original + signed copy + verify + log
- [ ] "Sign with" select (Token / Server-held key) appears only when a p12 is configured; server key signs without the extension
- [ ] Place stamp… renders the page; click places the dashed box; the stamp lands exactly there in the signed PDF (test a corner and mid-page)
- [ ] Place stamp on page 2 of 3 → stamp on page 2 only; default (no placement) → last page, bottom right
- [ ] pypdfium2 missing on the bench → Place stamp shows the pip install hint; signing with the default spot still works
- [ ] Success dialog → "Email signed copy" opens the standard composer: signed PDF attached, recipient prefilled from the doc's contact, verify link in the body
- [ ] "Copy verify link" puts the /os_verify URL on the clipboard; phone-scan of the stamp QR opens the same page, green badge, e-copy downloads
- [ ] Signature Log row shows Source File; list view still renders (no print format on file rows)
- [ ] Non-PDF attachment absent from the picker; direct API call with a txt File rejects with "Only PDF"
- [ ] Private attachment on a doc the user can't read → signing rejected with a permission error
- [ ] Sign a PDF page (no parent doc): upload → sign → signed copy + Log attach to the uploaded File itself
- [ ] Re-signing the same attachment creates a second signed copy (co-signing the signed file itself is Phase 9)
- [ ] Multi-select: dialog lists all PDF attachments as checkboxes (checked by default); tick 3 → one PIN prompt → 3 signed copies, 3 log rows, one timeline comment each
- [ ] Multi-select with dialog PIN → zero prompts; wrong PIN → nothing signed (fails at signHash, before any complete)
- [ ] Place stamp with 3 ticked → message asks to tick exactly one; tick one, place, re-tick the rest → placed file gets the click spot, others get last page bottom right
- [ ] Multi-select "Email signed copies" → one composer with all signed PDFs attached, one verify link per file in the body
- [ ] "Download copies" with 3 signed → browser takes all 3 downloads (staggered)
- [ ] MultiCheck Select All / Unselect All buttons work; two-column layout with 6+ attachments
- [ ] Stamp options collapsed by default; Position = Top left + Page = First page → stamp lands top left of page 1 on every ticked PDF
- [ ] QR checkbox off → stamp has no QR panel; verify link in the success dialog and email still opens /os_verify green
- [ ] Click placement + preset combo: placed file gets the clicked box, others follow the Position/Page presets
- [ ] Mid-batch failure (e.g. revoke read on file 2 between dialog and sign) → error names the failure, earlier signed copies kept and listed

## Auto-sign

- [ ] Auto Sign print format + `bench restart` → submitting a doc signs it in the background within a minute
- [ ] Break the p12 password → submit → failure appears in Error Log naming the doc; submit itself unaffected

## QR / verify page

- [ ] QR-enabled print format → stamp carries QR; phone-scan of a **printout** opens /os_verify
- [ ] Verify page shows green badge, signer, SHA-256; e-copy downloads without login
- [ ] Tampered code in URL → "Unknown verification code", no information leak
- [ ] Trust dir configured → "chains to a configured trust anchor"; without → "not checked" wording

## Evidence protection

- [ ] Non-System-Manager deletes the signed File attachment → refused with the Signature Log message
- [ ] Signature Log rows are read-only in desk (no Save, no Delete for admins via UI create)

## Regression (core)

- [ ] `python -m pytest core/ server/` green
- [ ] `bench --site <site> run-tests --app docsigner` green
