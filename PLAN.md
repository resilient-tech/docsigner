# Open Document Signer: Build Plan

An open-source stack for digitally signing PDFs with USB tokens (DSC), smartcards, or server-held keys. Python backend, JS everywhere else.

---

## 1. The shape of the system

Three rules the rest of the design follows from:

**The server does the heavy lifting.** It takes the PDF, builds the signature structure, computes a hash, and hands the browser a short session token plus that hash. The browser signs the hash and sends back the signature (~256 bytes). The server assembles the final PDF. The PDF never travels to the browser, which is what keeps the round trips down.

**The extension does zero crypto.** 3 layers: content script (bridges the page via CustomEvents), background service worker (routing), and a native app reached over Chrome native messaging (JSON on stdin/stdout). The native app talks PKCS#11 to the token, prompts for the PIN, and returns the signature. The private key never leaves the device.

**The page-facing API stays tiny.** A thin promise-based library: `init()`, `listCertificates()`, `sign()`. That is nearly the entire surface a page needs.

Out of scope on purpose: per-domain licensing, mobile pairing, a UI framework inside the extension, and any cloud dependency. pyHanko runs on your own server.

## 2. Architecture

5 pieces, all open source:

```
┌─────────────┐   HTTPS (hash + signature only)   ┌──────────────────┐
│  Web page    │◄─────────────────────────────────►│  Your server      │
│  + signer.js │                                    │  (Python, pyHanko)│
└──────┬──────┘                                     │  PDF stays here   │
       │ CustomEvent                                └────────┬─────────┘
┌──────▼──────┐                                              │
│  Extension   │                                    ┌────────▼─────────┐
│  (MV3)       │                                    │ Server-held key   │
└──────┬──────┘                                     │ (.p12 / HSM)      │
       │ native messaging (JSON/stdio)              │ same core lib     │
┌──────▼──────┐                                     └──────────────────┘
│ Native host  │
│ (Python +    │──PKCS#11──► USB token / smartcard
│  PyInstaller)│
└─────────────┘
```

1. **`signer-core`** (Python package). Wraps pyHanko. Owns: start/finish signing sessions, visual signature appearance, timestamps, LTV, validation, trust anchor config. Framework-agnostic. Usable directly from any Python app (including a future Frappe app).
2. **`signer-server`** (thin FastAPI reference server). 3 endpoints. Exists so people can run the thing in 5 minutes and so the JS lib has a contract to talk to.
3. **`signer-js`** (browser library, no dependencies). Three calls: `init`, `listCertificates`, `sign`. Talks to the extension via CustomEvents, falls back with a clear "install the extension" message.
4. **`signer-extension`** (WebExtension, Manifest V3). Content script + service worker + native messaging. One codebase runs on Chrome, Edge, Brave, Opera, and Firefox (Firefox supports MV3 and native messaging). Safari needs a macOS app wrapper; deferred.
5. **`signer-host`** (native messaging host). Python, shipped as a single PyInstaller binary per OS. Talks PKCS#11 to tokens via `python-pkcs11`. Handles PIN prompt (small native dialog). Installers drop the binary plus the browser manifest files.

Why pyHanko: it's the one mature Python library that covers PAdES B-B through B-LTA, and its "interrupted signing" mode is built for exactly our flow. You start signing, pause with a serializable state, get the digest out, and resume later with the signature bytes. It also validates signatures, which we get for free.

## 3. The signing flow

Token signing, end to end. This is the contract everything else is built around.

```
Page                    Server                       Extension → Host → Token
 │ listCertificates() ─────────────────────────────► certs (subject, issuer,
 │ ◄──────────────────────────────────── validity, thumbprint, DER)
 │ user picks cert
 │
 │ POST /signatures  {doc_id, certificate: <DER b64>, options}
 │ ─────────────────► pyHanko: prepare PDF revision,
 │                    build CMS signed attributes,
 │                    digest them, persist session
 │ ◄───────────────── {session_id, to_sign_hash, digest_algorithm}
 │
 │ sign({thumbprint, hash, algorithm}) ────────────► PKCS#11: PIN prompt,
 │ ◄────────────────────────────────── sign digest, return signature
 │
 │ POST /signatures/{session_id}/complete  {signature: <b64>}
 │ ─────────────────► pyHanko: finish CMS, embed in PDF,
 │                    optional RFC 3161 timestamp + LTV data
 │ ◄───────────────── {download_url}  (signed PDF)
```

Total data through the browser: one certificate (~2 KB), one hash (32 bytes), one signature (~256 to 512 bytes). A 200 MB PDF costs the same as a 200 KB one.

One subtlety worth pinning down now: the hash the token signs is the digest of the CMS *signed attributes*, which itself contains the document digest. pyHanko's interrupted signing hands us exactly that digest. The native host wraps it in a DigestInfo and signs with `CKM_RSA_PKCS` (or `CKM_ECDSA` raw for EC keys). No document bytes ever reach the token.

**Server-side signing** is the same `signer-core` code with a different signer: pyHanko's `SimpleSigner` loaded from a `.p12` file, or `PKCS11Signer` pointed at an HSM. One function call, no session dance, no extension involved.

## 4. Standards coverage (the multi-country story)

The good news: PDF signing converged internationally on one family of standards, so multi-country support is mostly configuration.

- **PAdES baseline profiles** (ETSI EN 319 142-1): B-B (basic), B-T (adds RFC 3161 timestamp), B-LT (embeds CRL/OCSP revocation data), B-LTA (adds archival timestamp chain). pyHanko supports all 4. These profiles are what eIDAS (EU), and by extension most national regulations, ask for.
- **India (CCA/ICP tokens: ePass2003, ProxKey, mToken, etc.)**: all ship PKCS#11 libraries with their drivers on Windows, macOS, and Linux. PAdES-signed PDFs validate in Adobe Reader against the CCA India root. Covered by the PKCS#11 path.
- **EU (eIDAS QES)**: smartcards and tokens again expose PKCS#11. Trust validation against EU trust lists is a server-side trust anchor question, handled in `signer-core` config.
- **Brazil (ICP-Brasil), Italy, others**: Country signature policies are, underneath, the same PAdES profiles plus country trust anchors. Same answer: PKCS#11 on the client, trust anchor set + profile choice on the server.
- **Timestamps**: any RFC 3161 TSA, URL configurable per deployment.
- **Algorithms**: RSA PKCS#1 v1.5 with SHA-256 as default (what nearly every DSC token uses), ECDSA supported from day one in the host since it's a few extra lines, RSA-PSS later.

So "supporting a country" means: its tokens speak PKCS#11 (they all do), and the server is configured with the right trust anchors and profile. Nothing country-specific in the extension or host.

## 5. Design decisions

**PKCS#11 only in v1.** Windows CAPI/CSP and macOS Keychain stay out of the first version. Every hardware token we care about installs a PKCS#11 module with its driver, so CAPI/Keychain adds surface without adding users. The host ships with a list of well-known module paths (ePass, ProxKey, WatchData, SafeNet, OpenSC covers most EU cards) and lets users add their own. OS keystore support is a later phase if demand shows up.

**Sessions live server-side, in files.** A start call writes the pyHanko pending-signature state plus the prepared PDF to a session directory with a random ID and a TTL. Finish reads it back. No database, no Redis. A deployment that needs shared storage across workers can mount the directory anywhere. `# ponytail: file-based sessions, swap for redis if multi-node`

**Origin consent, not licensing.** No paid domain gate: the first time a website origin asks for certificates, the extension shows a consent prompt, remembered per origin. Native host only accepts connections from our extension IDs (enforced by the browser's native messaging manifest anyway).

**One PIN, many signatures.** Batch signing keeps the PKCS#11 session open and signs N digests in one go. The API takes an array of hashes from the start. This is cheap now and painful to retrofit.

**The host is dumb on purpose.** List certificates, sign digest, done. All PDF knowledge, all policy, all validation lives on the server. That's what keeps the extension and host stable while the server grows features (CAdES later touches only Python).

**Errors are part of the API.** Token unplugged, wrong PIN, PIN locked, cert expired, user cancelled. Each gets a stable error code surfaced all the way to `signer-js`, because signing UX lives or dies on these messages.

## 6. Phases

### Phase 0: Spike (validate the risky bits before building anything)
- Monorepo scaffold: `core/`, `server/`, `js/`, `extension/`, `host/`, `.venv`, git, README skeleton.
- Script A: sign a PDF with pyHanko using a key in a `.p12`, validate in Adobe Reader.
- Script B: the interrupted-signing round trip against SoftHSM2 (a software PKCS#11 token): get digest out, sign via `python-pkcs11`, feed signature back, validate result.
- Script C: if you have a real DSC token, run script B against it.
- Exit: a token-signed PAdES B-B PDF that Adobe shows as valid. This de-risks the entire project in a few days.

### Phase 1: Core lib + server (server-side signing ships here)
- `signer-core`: `SigningSession.start(pdf, cert_der, options)` / `.complete(signature)`, plus `sign_with_server_key(pdf, p12, options)`. Visual appearance (text, image, position presets including a footnote preset). Trust anchor config as a PEM directory.
- `signer-server`: FastAPI, 3 endpoints (`POST /signatures`, `POST /signatures/{id}/complete`, `GET /documents/{id}`), file-based sessions, `.env` config.
- Exit: server-side signing usable in production for anyone whose key sits on the server. Real deliverable, not scaffolding.

### Phase 2: Native host
- `signer-host`: stdio JSON protocol (`listCertificates`, `signHash`, `getVersion`), `python-pkcs11` underneath, module autodiscovery from the known-paths list, PIN dialog, per-device PIN retry counts surfaced.
- A CLI test tool that speaks the same protocol from a terminal, so the host is fully testable without any browser.
- PyInstaller one-file builds for Windows, macOS, Linux. Install scripts that place the binary and write the native messaging manifests (registry on Windows, JSON files on macOS/Linux) for Chrome, Edge, and Firefox.
- Exit: `echo '{"command":"listCertificates"}' | signer-host` shows your token's certs on all 3 OSes.

### Phase 3: Extension + JS lib (token signing in the browser ships here)
- `signer-extension`: MV3, content script bridge (CustomEvent), service worker routing to the native host, origin consent prompt, host-not-installed detection with a download pointer.
- `signer-js`: `init()`, `listCertificates()`, `sign({sessionId or hash, thumbprint})`, promise-based, ~300 lines.
- Demo page wired to `signer-server`: pick file, pick cert, sign, download. This doubles as the integration doc.
- Exit: full browser flow on Chrome, Edge, and Firefox on all 3 OSes.

### Phase 4: Standards depth
- B-T: RFC 3161 timestamp on completion.
- B-LT / B-LTA: embed revocation data, archival timestamps.
- Multiple signatures on one PDF (incremental revisions; pyHanko handles this, we expose it).
- Batch signing end to end (one PIN prompt, N documents).
- Validation endpoint: upload a signed PDF, get signer info + validity per signature, powered by pyHanko's validator.
- Exit: signed output passes an independent validator (EU DSS demo validator) at each profile level.

### Phase 5: Distribution + polish
- Chrome Web Store + Firefox AMO listings. Edge picks up the Chrome listing.
- Signed installers: MSI (Windows), pkg (macOS), deb/rpm (Linux) for the host.
- Docs: integrate-in-10-minutes guide, self-hosting guide, token compatibility table.
- Optional, demand-driven: Safari wrapper app, Windows cert store support, CAdES detached signatures.

## 7. Testing

SoftHSM2 is the workhorse: a software PKCS#11 token that runs in CI, so the whole host + core round trip is tested on every commit without hardware. Real-token testing (ePass, ProxKey) stays a manual pre-release checklist. Signed PDFs get validated 3 ways: pyHanko's own validator in unit tests, Adobe Reader manually, and the EU DSS validator for profile conformance.

## 8. Risks, honestly

- **PyInstaller binaries are chunky** (~20-40 MB) and macOS wants them notarized, Windows wants them Authenticode-signed, or users see scary warnings. Budget for signing certificates in Phase 5. If binary size or startup time ever hurts, the host protocol is small enough to rewrite in Go without touching anything else.
- **Store review** for extensions using native messaging gets extra scrutiny. Submit early in Phase 5, expect a round trip or 2.
- **PKCS#11 module quality varies.** Some Indian token drivers are old and quirky (single-session locks, odd PIN behavior). The known-paths list plus per-token workarounds will grow by user report. Structure the host so quirks are data, config per module, and code stays generic.
- **Safari** has no cheap path (needs a signed macOS app). Parked until someone actually asks.

## 9. Repo layout

```
document-signer/
├── core/          # signer-core (pip package, pyHanko wrapper)
├── server/        # signer-server (FastAPI reference)
├── js/            # signer-js (browser lib, single file)
├── extension/     # signer-extension (MV3 WebExtension)
├── host/          # signer-host (native messaging, PyInstaller specs)
├── demo/          # demo page + sample PDFs
├── docs/
├── .venv/
├── .env.example
└── README.md
```

One repo, one issue tracker, releases tagged per component. Splitting into separate repos is a later problem, if ever.
