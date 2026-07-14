# signer-server

A small FastAPI reference server for OpenSigner. It holds the PDF, prepares the
signature, and hands the browser a 32-byte hash to sign, so the file never
leaves the server. It also signs directly with a server-held key. The signing
work is all `signer-core`; this package is the HTTP layer around it.

The routes and error codes are frozen in [`../CONTRACTS.md`](../CONTRACTS.md).

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
  LTV profiles (the root README covers the trust store).
- `P12_PATH` and `P12_PASSPHRASE` enable the server-held key that backs
  `/api/sign-server-side`.

Exported environment variables win over `.env` (it uses `setdefault`), so the
same file works in development and under a service manager.

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
