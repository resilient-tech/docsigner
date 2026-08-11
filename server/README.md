# signer-server

A small FastAPI reference server for DocSigner. It holds the PDF, prepares the
signature, and hands the browser a 32-byte hash to sign, so the file never
leaves the server. It also signs directly with a server-held key. The signing
work is all `signer-core`; this package is the HTTP layer around it.

How the flow works and what each module does:
[`../docs/server.md`](../docs/server.md). The routes and error codes are frozen
in [`../CONTRACTS.md`](../CONTRACTS.md).

## Run it

From the repo root (Python 3.10+):

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ./core -e ./server
cp .env.example .env                 # Windows: copy .env.example .env
python -m signer_server              # http://127.0.0.1:8001
```

`.env` is read from the directory you launch from, so run this from the repo
root where you copied it. Every setting is a plain environment variable; the
ones in `.env.example` cover storage and limits (`SESSION_DIR`, `DOCUMENT_DIR`,
the TTLs, `MAX_PDF_MB`). The rest you add as needed:

- `PORT` overrides the default 8001.
- `TSA_URL` sets the timestamp authority, `TRUST_DIR` the trust anchors for the
  LTV profiles (see below).
- `P12_PATH` and `P12_PASSPHRASE` enable the server-held key that backs
  `/api/sign-server-side`.

Exported environment variables win over `.env` (it uses `setdefault`), so the
same file works in development and under a service manager.

## Trust anchors for the LTV profiles

`TRUST_DIR` points at a folder of PEM or DER certificates, read recursively. The
repo ships one at `trust/`, organised by country and purpose, plus a script that
downloads everything in it from the CAs' own repositories:

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

Only self-signed certificates act as trust anchors. Intermediates in the folder
speed up chain building but are optional, since missing ones are fetched over the
certificates' AIA links.

The EU is the one region a folder of files cannot cover: its trust arrives as
signed per-country XML lists (EUTL, ETSI TS 119 612) and needs a parser, which
this repo doesn't have yet.

While completing a B-LT or B-LTA signature the server fetches revocation data
from the CA. OCSP is preferred (a response is 1 to 2 KB); CRLs are embedded only
for certificates without a good OCSP response, since Indian CA CRLs run to
megabytes. The CA's OCSP or CRL endpoints have to be reachable from the server.
If no revocation source answers, completion fails with an `INTERNAL` error, on
purpose: an LTV signature without revocation data would be an empty claim.

## Deploy it

`python -m signer_server` binds `127.0.0.1` with a single worker, which suits
local use and development. Behind a reverse proxy that terminates TLS, run
Uvicorn directly and add workers:

```bash
pip install -e ./core -e ./server
uvicorn signer_server.app:app --host 127.0.0.1 --port 8001 --workers 4
```

Keep the process bound to localhost and let the proxy (nginx, Caddy) handle TLS
and the public port. The CA's OCSP or CRL endpoints must be reachable from the
server for the LTV profiles to complete. Set the same env vars in the service
environment.

To build a wheel instead of installing by path:

```bash
pip install build && python -m build server
```

## Tests

```bash
pip install -e ./core -e ./server
pip install -r requirements-dev.txt
pytest server/tests
```

The whole HTTP flow is tested with in-memory keys, so no hardware or network is
required.
