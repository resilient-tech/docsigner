# Roadmap

What's left to build in **this** repo. The Frappe app has its own plan in
[frappe-app.md](frappe-app.md) and its own repo (`docsigner_integration`).

## Where we are

Working end to end. Signed output validates as PAdES, in Adobe and in the EU DSS
validator. Server-side signing, token signing through the browser, and the
desktop batch app all run. Not yet published to the extension stores.

Shipped: the signing engine, the reference server, the native host (rewritten in
Rust), the extension and page library, the desktop app, standards depth up to
B-LTA and the CCA profiles, and the device-layer diagnostics that came out of the
first live week.

## Open: core

| # | What | Files |
|---|------|-------|
| C1 | **Marks on every page.** A visible mark (name, date, page x of y) on all pages plus the one cryptographic field, in one incremental revision. | new `core/docsigner_core/marks.py` |
| C2 | **Caption line on the stamp.** "Reviewed by" / "Approved by" above the name. Additive appearance field, needs a CONTRACTS changelog entry. | `core/docsigner_core/appearance.py` |

Both are asked for by the Frappe app's phases 9 and 9.5, so they land here first.

## Open: distribution

The long poles. Nothing else depends on them, but the lead times are weeks.

| # | What | Notes |
|---|------|-------|
| D1 | **Extension listings.** Chrome Web Store and Firefox AMO. Store copy from the README, privacy answers from CONTRACTS (no analytics, no remote calls). | Native messaging draws extra review scrutiny. Submit early. |
| D2 | **Host installers.** pkg, MSI, deb/rpm. | macOS no longer waits on a certificate: the Homebrew formula installs unquarantined, so a notarized pkg is a convenience, not the gate. An unsigned MSI works too and only shows "Unknown publisher"; D7 removes that. |
| D3 | **Update channel.** Wire the host's existing `checkUpdate` into the extension consent page. | The host side already works. |
| D4 | **Token compatibility table.** Seeded from the known lists in `modules.rs` and `pcsc_readers.rs`. | Grows by user report. |
| D5 | ~~**A license file.**~~ Done: Apache-2.0, with `NOTICE` for Lucide and the fonts. | Every manifest declares it and the Homebrew formula carries `license "Apache-2.0"`. The cask has no license stanza to fill; Homebrew does not define one. |
| D6 | **A tap repo.** `resilient-tech/homebrew-tap`, with `Formula/` and `Casks/`. The release attaches both files with their checksums already filled in, so each release is a copy of two files. | Waits on the repo going public, same as D7. Until then the files are validated in place with a throwaway tap: `brew tap-new --no-git`, copy them in, `brew style`. |
| D7 | **Windows code signing, free.** Apply to [SignPath Foundation](https://signpath.org) for a certificate at no cost, then sign the host and the desktop `.exe` in CI. | **Needs the repo public first**, plus an OSI license (D5) and a reproducible CI build. They review by hand and it takes a couple of weeks, so apply the day the repo opens. Once signed, the MSI in D2 stops saying "Unknown publisher". |

Before any of it: real-token runs on all 3 operating systems, per
[release-checklist.md](release-checklist.md).

## What live testing taught us

From the first week on a real bench with a real Capricorn token (2026-07-08).
Each of these is fixed; they're here because they say what to watch for.

- **An empty certificate list has to explain itself.** The page library was
  dropping the host's `readers` array, so every failure showed the same generic
  "plug in your token" hint. `listCertificates()` now returns
  `{certificates, readers, diagnostics}` and the host reports per-source scan
  counters, so the hint names the actual cause.
- **Token drivers wedge.** ePass/ProxKey-class drivers allow one process on the
  token at a time, and some only enumerate at `C_Initialize`. Covered by a
  reinitialize per scan, a 20-second watchdog per module, and competing-process
  detection that names the program to close.
- **SHA-512 worked; the display lied.** The verify page labelled the file
  fingerprint "SHA-256" and never showed the signature digest.
- **Ten handwriting fonts was too many.** Trimmed to 5, one per personality.

## What's deliberately not on this list

Safari (needs a signed macOS app wrapper), EU trust lists (needs an EUTL XML
parser), RSA-PSS, and a database-backed session store. Reasons are in
[architecture.md](architecture.md) under "What we skipped, on purpose". Each one
moves onto this list the day someone actually needs it.
