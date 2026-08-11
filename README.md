# OpenSigner

Open-source digital signatures for PDFs. Sign with a USB token (DSC) or smartcard from any website, or with a key held on your own server. Python backend, plain JS everywhere else.

The design follows a simple rule: the PDF never leaves the server. The browser only carries a 32-byte hash out and a ~256-byte signature back. A 200 MB file signs as fast as a 200 KB one.

Status: working end to end. Signed output validates as PAdES. Not yet published to extension stores.

## How it works

```
Web page ──(cert, 32-byte hash, signature)── Your server (pyHanko, PDF stays here)
   │
Extension ──(native messaging)── opensigner-host ──(PKCS#11)── USB token
```

1. The page asks the extension for the user's certificates. The extension asks `opensigner-host`, a small native app that reads them from the token over PKCS#11.
2. The page sends the chosen certificate to your server. The server prepares the signature inside the PDF and returns the hash to sign.
3. The token signs the hash (PIN prompt happens in the native app, the PIN never touches the browser or the network).
4. The server embeds the signature and hands back a download link.

Server-held keys skip steps 1 and 3: one call to `/api/sign-server-side` with a `.p12` configured.

## What's in this repo

| Folder | What it is |
|---|---|
| `core/` | `signer-core`, the Python signing library (pyHanko underneath) |
| `server/` | `signer-server`, a small FastAPI reference server |
| `js/` | `opensigner.js`, the page-side library (single file, no deps) |
| `extension/` | WebExtension (Manifest V3) for Chrome, Edge, Brave, Firefox |
| `host-rs/` | `opensigner-host`, the native messaging binary that talks to tokens (Rust, ~1 MB) |
| `desktop/` | `opensigner-desktop`, a local app to batch-sign a folder of PDFs with a placed signature |
| `demo/` | A working demo page, also the integration example |
| `spike/` | Phase 0 proof scripts, kept as executable documentation |
| `CONTRACTS.md` | The frozen protocol between all components |
| `PLAN.md` | The build plan and architecture decisions |

The Frappe/ERPNext app lives in its own repo, `opensigner_integration`: sign print formats from the desk, bulk one-PIN signing, auto-sign on submit, QR verification e-copies. It embeds `core/` as a pip dependency; its build plan and live-test checklist are in `plan/` here.

Standards: PAdES baseline profiles per ETSI EN 319 142-1, plus CCA-LTV and CCA-LTA per CCA India's Electronic Signature Application Integration Guidelines (PKCS#7 with revocation data in the pdfRevocationInfoArchival signed attribute, ESAIG 1.19). All PDF profiles work in both flows, token sessions and server-side signing. Beyond PDF: detached CAdES-BES (.p7s) over any file in both flows, and enveloped XAdES-B over XML with the server-held key. Timestamps come from `TSA_URL` or a per-request pick from the built-in registry (DigiCert, Sectigo, Certum, Entrust, SSL.com); a paid authority that wants credentials takes `TSA_AUTH` or `TSA_BEARER`, which are sent only to `TSA_URL`. For PKIs that grade signatures on a policy attribute rather than the ETSI baseline, `options.policy` embeds a signature policy identifier; ICP-Brasil's four PAdES policies ship as names and `POLICY_DIR` holds the artifacts they hash. PDF/A input is detected and reported so an invisible signature can keep conformance intact. The LTV profiles need `TRUST_DIR`, and the CA's OCSP or CRL endpoints must be reachable from the server. RSA and ECDSA keys, SHA-256/384/512.

## Run the server

Works on Linux, macOS, and Windows. Needs Python 3.10 or newer. Use `python3` on Linux/macOS, `python` on Windows.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ./core -e ./server
cp .env.example .env             # Windows: copy .env.example .env
python -m signer_server          # http://127.0.0.1:8001, override with PORT in .env
```

`.env` is read from the directory you launch the server in. Run `python -m signer_server` from the repo root so it picks up the `.env` you just copied.

### Trust anchors for the LTV profiles

`TRUST_DIR` points at a folder of PEM or DER certificates, read recursively. The repo ships one at `trust/`, organised by country and purpose, and a script that downloads everything in it from the CAs' own repositories:

```bash
python scripts/fetch_trust_roots.py
```

```
trust/
  in/       CCA India roots + all 21 licensed CA certificates from CCA's registry
  br/       ICP-Brasil roots
  us/       US Federal PKI root
  tsa/      roots for the timestamp authority in TSA_URL (DigiCert)
  archive/  expired root generations, skipped by the loader; move one up to
            validate documents signed under it
```

Only self-signed certificates act as trust anchors; intermediates found in the folder speed up chain building but are optional, since missing ones are fetched over the certificates' AIA links. The EU is the one region a folder of files cannot cover: its trust arrives as signed per-country XML lists (EUTL, ETSI TS 119 612) and needs a parser, which this repo does not have yet.

While completing a B-LT or B-LTA signature the server fetches revocation data from the CA. OCSP is preferred (a response is 1 to 2 KB); CRLs are embedded only for certificates without a good OCSP response, since Indian CA CRLs run to megabytes. If no revocation source answers, completion fails with an `INTERNAL` error: an LTV signature without revocation data would be an empty claim.

## Run the desktop app

`desktop/` is a standalone local app: load a folder, place one signature by dragging it onto the page, and batch-sign every PDF with a token (one PIN for the whole batch) or a server-held key. Nothing is uploaded. It reuses `core/` and `host/`, and picks up the `trust/` store above it automatically. Setup and run steps are in [`desktop/README.md`](desktop/README.md).

## Try the demo

With the server running, serve the repo root (the demo imports `js/opensigner.js` from its sibling folder, and browsers block `file://` fetch):

```bash
python3 -m http.server 8080
```

Open http://localhost:8080/demo/. To sign with a token you also need the extension and the host installed (next 2 sections). Server-side signing needs neither.

## Install the extension (development)

Chrome / Edge / Brave: open `chrome://extensions`, enable Developer mode, Load unpacked, pick `extension/`. Note the extension ID it gets, the host installer needs it.

Firefox: run `python scripts/build_firefox_extension.py` first (Firefox runs the background as an event page, and Chrome refuses a manifest that declares one, so the Firefox copy is generated). Then `about:debugging` → This Firefox → Load Temporary Add-on → pick `dist/firefox-extension/manifest.json`. Firefox also asks you to grant site access per site in the extension's settings.

## Install the native host

The host is a self-contained Rust binary of about 1 MB. It needs no runtime, only your token's driver installed (the driver ships the PKCS#11 module the host loads).

Build it:

```bash
cargo build --release --manifest-path host-rs/Cargo.toml
```

```bash
host-rs/target/release/opensigner-host list    # should print your token's certificates
```

Then register it with your browsers (pass your extension ID):

```bash
host-rs/packaging/install.sh <chrome-extension-id>     # macOS / Linux
host-rs\packaging\install.bat <chrome-extension-id>    # Windows
```

The installer copies the binary and writes the native messaging manifests for Chrome, Chromium, Edge, Brave, and Firefox. Details, including the driver quirks the host works around, are in [`host-rs/README.md`](host-rs/README.md).

### Token support

The host also reports connected smart-card readers through the OS smart-card service (PC/SC), which sees the token even when its driver is missing — so `opensigner-host list` can tell you "ProxKey detected, driver not installed" instead of showing nothing. How the strategies compare across products: `docs/host.md`.

Two discovery paths, merged into one certificate list:

**OS certificate store** (macOS and Windows). Most token drivers register the token's certificate with the Keychain or the Windows `MY` store on install, and the host reads those directly — no driver path needed. Signing routes back through the same OS API (Keychain / CNG), which forwards it to the token; the OS shows its own PIN dialog. Linux has no universal OS store, so there PKCS#11 is the only path.

**PKCS#11 drivers.** Any device with a PKCS#11 driver. Known module paths ship for OpenSC, ePass2003, WatchData ProxKey, SafeNet eToken, and eMudhra tokens. Yours somewhere else? Point the env var at it:

```bash
export OPENSIGNER_PKCS11_MODULES=/path/to/your/pkcs11.so
```

or add it to `~/.config/opensigner/modules.json` (`%APPDATA%\opensigner\modules.json` on Windows).

## Use it from your own page

```html
<script type="module">
  import { OpenSigner } from "./js/opensigner.js";
  const signer = new OpenSigner();
  await signer.init();
  const certs = await signer.listCertificates();
  // POST /api/signatures with your PDF + certs[i].certificate,
  // sign the returned hash:
  const { signatures } = await signer.signHash({
    thumbprint: certs[0].thumbprint,
    hashes: [toSignHash],
    digestAlgorithm: "sha256",
  });
  // POST /api/signatures/{session_id}/complete with signatures[0]
</script>
```

`demo/demo.js` is the full worked example, including error handling for every error code in `CONTRACTS.md`.

## Tests

```bash
pip install -e ./core -e ./server              # if not already installed
pip install -r requirements-dev.txt            # pytest + test-only deps
pytest core/tests server/tests                 # 76 tests
PYTHONPATH=desktop/backend pytest desktop/backend/tests   # 11 tests
cargo test --manifest-path host-rs/Cargo.toml  # 72 tests
cd js && node --test                           # 10 tests
```

Everything runs without hardware: the whole HTTP flow is tested with in-memory keys, and the host's tests assert invariants that hold whether or not a token is plugged in. Testing with a real DSC token is a manual step before releases: plug it in, run `opensigner-host list`, then sign through the demo. The end-to-end suite has a gated real-token path, `OPENSIGNER_E2E_REAL_TOKEN=1 pytest e2e/test_host_e2e.py`.

## Before publishing

Things this repo still needs before a public release: a license file (pick one), extension store listings, signed host binaries (Authenticode on Windows, notarization on macOS), and real-token runs on all 3 OSes. `PLAN.md` phase 5 has the details.
