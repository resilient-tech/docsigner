# DocSigner

Open-source digital signatures for PDFs. Sign with a USB token (DSC) or
smartcard from any website, or with a key held on your own server. Python
backend, plain JS everywhere else.

One rule shapes the design: **the PDF never leaves the server.** The browser
carries a 32-byte hash out and a ~256-byte signature back, so a 200 MB file signs
as fast as a 200 KB one.

Status: working end to end. Signed output validates as PAdES. Not yet published
to the extension stores.

## How it works

```
Web page ──(cert, 32-byte hash, signature)── Your server (pyHanko, PDF stays here)
   │
Extension ──(native messaging)── docsigner-host ──(PKCS#11)── USB token
```

1. The page asks the extension for the user's certificates. The extension asks
   `docsigner-host`, a small native app that reads them from the token.
2. The page sends the chosen certificate to your server. The server prepares the
   signature inside the PDF and returns the hash to sign.
3. The token signs the hash. The PIN prompt happens in the native app, so the PIN
   never touches the browser or the network.
4. The server embeds the signature and hands back a download link.

Server-held keys skip steps 1 and 3: one call to `/api/sign-server-side`.

The longer version, with the design decisions and why:
[`docs/architecture.md`](docs/architecture.md).

## Run it

Linux, macOS, and Windows. Needs Python 3.10 or newer. Use `python3` on
Linux/macOS, `python` on Windows.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ./core -e ./server
cp .env.example .env             # Windows: copy .env.example .env
python -m docsigner_server          # http://127.0.0.1:8001
```

Run it from the repo root, since `.env` is read from the directory you launch in.

Then serve the repo root and open the demo (browsers block `file://` fetch, and
the demo imports `js/docsigner.js` from its sibling folder):

```bash
python3 -m http.server 8080      # then open http://localhost:8080/demo/
```

Server-side signing works right there. To sign with a token you also need the
extension ([`extension/README.md`](extension/README.md)) and the native host
([`host-rs/README.md`](host-rs/README.md)) installed.

Prefer a desktop app to a browser? [`desktop/README.md`](desktop/README.md)
batch-signs a folder with no server and no extension.

## What's in this repo

| Folder | What it is | Read first |
|---|---|---|
| `core/` | `docsigner-core`, the Python signing library (pyHanko underneath) | [docs/core.md](docs/core.md) |
| `server/` | `docsigner-server`, the HTTP API + `server/openapi.json` | [docs/server.md](docs/server.md) |
| `host-rs/` | `docsigner-host`, the native binary that talks to tokens (Rust, ~1 MB) | [docs/host.md](docs/host.md) |
| `desktop/` | `docsigner-desktop`, batch-sign a folder locally | [docs/desktop.md](docs/desktop.md) |
| `extension/` | WebExtension (MV3) for Chrome, Edge, Brave, Firefox | [extension/README.md](extension/README.md) |
| `js/` | `docsigner.js`, the page-side library (one file, no deps) | [js/README.md](js/README.md) |
| `demo/` | A working demo page, and the integration example | |
| `trust/` | Trust anchors for the LTV profiles | [server/README.md](server/README.md#trust-anchors-for-the-ltv-profiles) |
| `spike/` | Phase 0 proof scripts, kept as executable documentation | |

Two things sit above all of it:

- [`CONTRACTS.md`](CONTRACTS.md) — every wire format, frozen. HTTP routes, native
  messaging commands, the page bridge, error codes.
- [`docs/`](docs/README.md) — the index, and how the docs are organised.

The Frappe/ERPNext app lives in its own repo, `docsigner_integration`: sign print
formats from the desk, bulk one-PIN signing, auto-sign on submit, QR verification
e-copies. It embeds `core/` as a pip dependency. Its plan is in
[`docs/frappe-app.md`](docs/frappe-app.md) until that repo takes a copy.

## Standards

PAdES B-B through B-LTA per ETSI EN 319 142-1, plus CCA-LTV and CCA-LTA for
India. Detached CAdES-BES over any file, and enveloped XAdES-B over XML. RSA and
ECDSA, SHA-256/384/512. Full coverage and the country story:
[`docs/architecture.md`](docs/architecture.md#standards).

## Tests

```bash
pip install -e ./core -e ./server
pip install -r requirements-dev.txt
pytest core/tests server/tests
PYTHONPATH=desktop/backend pytest desktop/backend/tests
cargo test --manifest-path host-rs/Cargo.toml
cd js && node --test
```

Everything runs without hardware: the HTTP flow is tested with in-memory keys,
and the host's tests assert invariants that hold whether or not a token is
plugged in. The end-to-end suite has a gated real-token path,
`DOCSIGNER_E2E_REAL_TOKEN=1 pytest e2e/test_host_e2e.py`.

Testing with a real token before a release is a manual step, and the list is
[`docs/release-checklist.md`](docs/release-checklist.md).

## Before publishing

A license file (pick one), extension store listings, signed host binaries
(Authenticode on Windows, notarization on macOS), and real-token runs on all 3
operating systems. Details in [`docs/roadmap.md`](docs/roadmap.md).
