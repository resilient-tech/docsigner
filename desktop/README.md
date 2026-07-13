# OpenSigner Desktop

A local desktop app to sign PDFs with a visible signature you place yourself. Load a folder, drag the signature where you want it, resize it, and sign every PDF at once. Signed copies land back in the same folder with a suffix. Nothing is uploaded.

The signing engine is OpenSigner's `signer-core` (pyHanko underneath), reused in-process. The UI is built in the Sunsama-inspired design language.

## What works today

- Choose a folder or specific PDFs with a native picker (or paste a path).
- Pick which files to sign with checkboxes; the rest are left alone.
- Place the signature: drag the box to move it, drag a corner to resize. The on-page box shows the signature exactly as it lands (navy ink, scaled to the box), so what you see is what gets signed. One location covers the whole batch.
- Sign with a DSC token or a server-held key. One login signs the whole batch, so the PIN is asked once for the folder.
- Appearance the way Acrobat does it: handwritten name (the real bundled fonts), date, reason, location. Saved under a name, editable.
- Standards: PAdES B-B, B-T (RFC 3161 timestamp), B-LT (LTV, embedded revocation), and CCA-LTV for India. Timestamp authority and trust anchors are configurable.
- Bulk sign: signed copies are written beside the originals as `name_signed.pdf`.
- Responsive from tablet to large screens.

## Signing identity

Two kinds, listed together in the certificate menu:

- **DSC token** (the main path). The OpenSigner host reads the token's certificates over PKCS#11 and signs them. It runs as a fresh subprocess per call (the model the browser extension uses), which sidesteps the per-process slot state some token drivers cache and would otherwise wedge a long-lived scan. One login signs the whole batch, so the PIN is asked once.
- **Server-held key** (`.p12`). A self-signed test key is created on first run under `~/.config/opensigner-desktop/signing-keys/` so the app runs without a token; drop your own `.p12` there to use it.

## Fonts

The handwriting faces are the OFL fonts signer-core embeds into the PDF (bundled from core), so the preview matches the output. System fonts are deliberately not offered: the signer can only embed a face it ships, and a preview in a font the signed file cannot use would mislead.

## Run it

Backend (Python 3.12):

```bash
cd backend
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m opensigner_desktop      # http://127.0.0.1:8000
```

Frontend:

```bash
cd frontend
pnpm install
pnpm dev                                       # proxies /api to the backend
```

For a single-process build, run `pnpm build` in `frontend/`, then start the backend: it serves `frontend/dist` at `/`.

Timestamp and trust (for B-T and up) come from `OPENSIGNER_TSA_URL` (default DigiCert) and `OPENSIGNER_TRUST_DIR`. If the OpenSigner repo's `trust/` folder sits nearby it is picked up automatically.

## How it signs (one PIN, many files)

For each file the backend prepares the signature and converts your fractional placement into PDF points for that page (so one placement stays correct across page sizes). For a token, every hash is signed in a single PKCS#11 session behind one PIN; for a server key each is signed directly. B-T adds an RFC 3161 timestamp; B-LT and CCA embed revocation gathered against the trust anchors. The signature is embedded and the file written with the suffix.

## Optional: signing from a web page

The desktop app reaches the token directly through the host, so it needs no browser extension. The same host also backs OpenSigner's browser extension, so a web-only demo (a page that signs through the extension instead of a local backend) is a clean addition later: the token path underneath is identical.

## Layout

```
backend/opensigner_desktop/
  app.py        FastAPI routes
  render.py     page image + page size (pypdfium2)
  signing.py    bulk sign via signer-core; placement -> points; appearance mapping
  certs.py      signing identities (.p12); self-signed test key on first run
  store.py      settings + appearance profiles (the "remembered" layer)
  models.py     request / response shapes
frontend/src/
  components/PlacementCanvas.tsx   drag + resize the signature box
  components/SetupPanel.tsx        certificate, profile, standard, output
  components/ProfileEditor.tsx     Acrobat-style appearance profiles
  components/StampPreview.tsx      live stamp preview
  App.tsx  api.ts  types.ts  tokens.css
```
