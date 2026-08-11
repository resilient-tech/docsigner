# DocSigner Desktop

A local app for signing a folder of PDFs at once, with a signature you place
yourself. Nothing is uploaded. The signing engine is DocSigner's `signer-core`
(pyHanko underneath), reused in-process. The UI is built in the Sunsama-inspired
design language.

What it does, the two signing identities, the stamp and the module map:
[`../docs/desktop.md`](../docs/desktop.md). This file is build and packaging.

## Development

The venv and Python here are for building and hacking on the app. Whoever
*installs* the packaged app needs neither (see [Production](#production--build-an-installable-app)).

Build the frontend once (the window loads the built UI), then run the app on
Python 3.12:

```bash
cd frontend && pnpm install && pnpm build

cd ../backend
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt    # also installs ../../core
./.venv/bin/python -m docsigner_desktop        # opens the native window
```

To iterate on the UI with hot reload, run the backend headless and point Vite at it:

```bash
./.venv/bin/python -m docsigner_desktop --server   # http://127.0.0.1:8000
cd ../frontend && pnpm dev                         # proxies /api and /fonts to :8000
```

Backend tests (token cache, host seam) need only `cryptography`:

```bash
./.venv/bin/python -m pytest tests -q
```

### Environment

| Variable | Effect |
|---|---|
| `DOCSIGNER_HOST_BIN` | point at a different signing host |
| `DOCSIGNER_TSA_URL` | default timestamp authority (the app's own setting wins) |
| `DOCSIGNER_TRUST_DIR` | trust anchors for B-LT and the CCA profiles |

The host binary has to speak the same CLI (`list`, `sign`, `version`) and print
the same JSON. That's how the Rust host is exercised against the real app:

```bash
DOCSIGNER_HOST_BIN=../../host-rs/target/release/docsigner-host \
    ./.venv/bin/python -m docsigner_desktop --server
```

If the repo's `trust/` folder sits nearby it's picked up automatically, and the
packaged app carries its own copy.

## Production — build an installable app

The packaged app is self-contained: PyInstaller embeds CPython and every
dependency (FastAPI, pyHanko, pypdfium2, cryptography) and bundles the built
frontend and the `trust/` anchors. The window is drawn with the OS's native
webview, so there is no Chromium to ship (Electron would only add ~150 MB for the
same result). The user double-clicks; no Python, pip, or venv on their machine.
The token host runs by re-execing the app itself (`--host-cli`), so token signing
works with no Python present.

Build on the OS you are targeting. PyInstaller does not cross-compile.

### macOS — `.app` and `.dmg`

```bash
./build-macos.sh          # -> backend/dist/DocSigner.app  and  DocSigner.dmg
```

Builds the frontend, sets up the venv, runs PyInstaller with
`packaging/docsigner-desktop.spec`, then packs a drag-to-Applications `.dmg` with
`hdiutil` (built into macOS, no extra tool). Hand out the `.dmg`.

### Windows — `.exe`

Run the same spec on a Windows machine (Python 3.12 + Node/pnpm installed):

```bat
cd frontend && pnpm install && pnpm build
cd ..\backend
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm ..\packaging\docsigner-desktop.spec
```

That writes `backend\dist\docsigner-desktop\` with `docsigner-desktop.exe` inside.
Zip that folder to hand it out, or wrap it in an installer with Inno Setup or NSIS
for a Start-menu entry. WebView2 (the window runtime) ships with Windows 11 and
installs automatically on Windows 10. (This path is set up but built only on
macOS so far; confirm it on a real Windows box.)

### Linux

The spec produces `backend/dist/docsigner-desktop/` (a folder with the binary).
Ship the folder, or wrap it as an AppImage for a single portable file. The window
needs WebKitGTK, present on most desktops.

### Before you distribute

- **Signing.** `build-macos.sh` ad-hoc signs the app so it launches on Apple
  Silicon, but ad-hoc is not a Developer ID: macOS Gatekeeper and Windows
  SmartScreen still warn on a *downloaded* copy. For a clean install, sign and
  notarize with an Apple Developer ID on macOS and an Authenticode certificate on
  Windows. Until then, the recipient clears the warning once. On recent macOS the
  right-click → Open trick is often gone; use System Settings → Privacy &
  Security → "Open Anyway", or run `xattr -dr com.apple.quarantine DocSigner.app`.
- **Token driver.** The DSC vendor's PKCS#11 middleware must be installed on the
  user's machine, the same as for the Frappe flow or the browser extension. It is
  hardware middleware and cannot ride inside the app.
- **App icon.** `packaging/DocSigner.icns`, generated from the one logo source
  `assets/icon.svg` by `scripts/make_assets.py` along with the extension and host
  icons. macOS caches icons hard, so a rebuilt app can still show the old one in
  Finder or the Dock: `killall Dock Finder`, or move the app once, to refresh.

Verify a build by opening it and signing one PDF with the actual token. That pops
the token PIN, which only the token holder can enter.
