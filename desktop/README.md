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

## Development

The venv and Python here are for building and hacking on the app. Whoever *installs*
the packaged app needs neither (see [Production](#production--build-an-installable-app)).

Build the frontend once (the window loads the built UI), then run the app on Python 3.12:

```bash
cd frontend && pnpm install && pnpm build

cd ../backend
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt    # also installs ../../core and ../../host
./.venv/bin/python -m opensigner_desktop        # opens the native window
```

To iterate on the UI with hot reload, run the backend headless and point Vite at it:

```bash
./.venv/bin/python -m opensigner_desktop --server   # http://127.0.0.1:8000
cd ../frontend && pnpm dev                           # proxies /api and /fonts to :8000
```

Timestamp and trust (for B-T and up) come from `OPENSIGNER_TSA_URL` (default DigiCert)
and `OPENSIGNER_TRUST_DIR`. If the OpenSigner repo's `trust/` folder sits nearby it is
picked up automatically, and the packaged app carries its own copy.

## Production — build an installable app

The packaged app is self-contained: PyInstaller embeds CPython and every dependency
(FastAPI, pyHanko, pypdfium2, cryptography) and bundles the built frontend and the
`trust/` anchors. The window is drawn with the OS's native webview, so there is no
Chromium to ship (Electron would only add ~150 MB for the same result). The user
double-clicks; no Python, pip, or venv on their machine. The token host runs by
re-execing the app itself (`--host-cli`), so token signing works with no Python present.

Build on the OS you are targeting (PyInstaller does not cross-compile).

### macOS — `.app` and `.dmg`

```bash
./build-macos.sh          # -> backend/dist/OpenSigner.app  and  OpenSigner.dmg
```

Builds the frontend, sets up the venv, runs PyInstaller with
`packaging/opensigner-desktop.spec`, then packs a drag-to-Applications `.dmg` with
`hdiutil` (built into macOS, no extra tool). Hand out the `.dmg`.

### Windows — `.exe`

Run the same spec on a Windows machine (Python 3.12 + Node/pnpm installed):

```bat
cd frontend && pnpm install && pnpm build
cd ..\backend
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm ..\packaging\opensigner-desktop.spec
```

That writes `backend\dist\opensigner-desktop\` with `opensigner-desktop.exe` inside.
Zip that folder to hand it out, or wrap it in an installer with Inno Setup or NSIS for
a Start-menu entry. WebView2 (the window runtime) ships with Windows 11 and installs
automatically on Windows 10. (This path is set up but built only on macOS so far;
confirm it on a real Windows box.)

### Linux

The spec produces `backend/dist/opensigner-desktop/` (a folder with the binary). Ship
the folder, or wrap it as an AppImage for a single portable file. The window needs
WebKitGTK, present on most desktops.

### Before you distribute

- **Signing.** Unsigned, macOS Gatekeeper and Windows SmartScreen warn on first launch.
  For a smooth install, sign and notarize with an Apple Developer ID on macOS and an
  Authenticode certificate on Windows. Until then, users do right-click → Open once
  (macOS: `xattr -dr com.apple.quarantine OpenSigner.app`).
- **Token driver.** The DSC vendor's PKCS#11 middleware must be installed on the user's
  machine, the same as for the Frappe flow or the browser extension. It is hardware
  middleware and cannot ride inside the app.

Verify a build by opening it and signing one PDF with the actual token — that pops the
token PIN, which only the token holder can enter.

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
