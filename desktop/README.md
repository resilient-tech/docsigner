# DocSigner Desktop

A local app for signing a folder of PDFs at once, with a signature you place
yourself. Nothing is uploaded. The signing engine is DocSigner's `docsigner-core`
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
cd ../frontend && pnpm dev                         # proxies /api and /font-file to :8000
```

Backend tests (token cache, host seam, pickers) need only `cryptography`, but
pytest itself is not in `requirements.txt` — that file is what the packaged app
ships, so the test tooling lives in the repo's dev list instead:

```bash
./.venv/bin/pip install -r ../../requirements-dev.txt
./.venv/bin/python -m pytest tests -q
```

### Environment

| Variable              | Effect                                                   |
| --------------------- | -------------------------------------------------------- |
| `DOCSIGNER_HOST_BIN`  | point at a different signing host                        |
| `DOCSIGNER_TSA_URL`   | default timestamp authority (the app's own setting wins) |
| `DOCSIGNER_TRUST_DIR` | trust anchors for B-LT and the CCA profiles              |

The host binary has to speak the same CLI (`list`, `sign`, `version`) and print
the same JSON. That's how the Rust host is exercised against the real app:

```bash
DOCSIGNER_HOST_BIN=../../host/target/release/docsigner-host \
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
The token host is its own ~1 MB Rust binary carried alongside as a sidecar, so
token signing works with no Python present.

Build on the OS you are targeting. PyInstaller does not cross-compile.

### macOS — `.app` and `.dmg`

Needs Rust, and an **x86_64** CPython 3.12 even on an Apple Silicon Mac:

```bash
uv python install cpython-3.12-macos-x86_64    # ~24 MB; raise UV_HTTP_TIMEOUT on a slow link
./build-macos.sh                               # -> backend/dist/DocSigner.app  and  DocSigner.dmg
```

Everything is built x86_64 on purpose. The sidecar host has to be, since it is
the only process that loads a PKCS#11 module and an arm64 process cannot load an
x86_64-only driver. Given that, Rosetta is already required on Apple Silicon, so
the `.app` matches and keeps working on Intel Macs too. The script verifies both
binaries with `file` and refuses to package a mismatch, and the header comment
carries the full argument.

One consequence worth knowing before you bump dependencies: `cryptography` 49
dropped macOS x86_64 and universal2 wheels, so `backend/requirements.txt` pins it
below that. Without the pin, pip reaches for the sdist and the build dies needing
an x86_64 OpenSSL to compile against.

Builds the frontend and the sidecar, sets up the venv, runs PyInstaller with
`packaging/docsigner-desktop.spec`, then packs a drag-to-Applications `.dmg` with
`hdiutil` (built into macOS, no extra tool). Hand out the `.dmg`.

The script prints the `.dmg`'s SHA-256 at the end. That goes into
`packaging/homebrew/docsigner.rb`, the cask, which is how the app installs
without an Apple Developer ID:

```bash
brew install --cask --no-quarantine resilient-tech/tap/docsigner
```

`--no-quarantine` is part of the install line, not a suggestion. Homebrew stamps
`com.apple.quarantine` on every cask and only releases it when asked, so without
the flag an ad-hoc signed app is exactly what Gatekeeper blocks. With it, the app
opens on the first double-click. Copy the cask into the tap repo
(`resilient-tech/homebrew-tap`, as `Casks/docsigner.rb`) and bump `version` and
`sha256` when tagging.

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
installs automatically on Windows 10.

`.github/workflows/release.yml` runs exactly this on a `windows-latest` runner
and publishes the zip, so a release needs no Windows machine. Opening the result
still does: nobody has launched it, and the Windows certificate-store path in the
host is unrun code. Treat the artifact as untested until someone signs a PDF with
a token in it.

### Linux

The spec produces `backend/dist/docsigner-desktop/` (a folder with the binary).
Ship the folder, or wrap it as an AppImage for a single portable file. The window
needs WebKitGTK, present on most desktops.

The release workflow builds it on `ubuntu-22.04` and publishes the tarball. It
installs the GTK/WebKit development packages and `pygobject` in the job, since
`requirements.txt` carries neither: that file serves the macOS build, where the
window is pyobjc. Untested for the same reason as the Windows build.

### Before you distribute

- **Signing.** `build-macos.sh` ad-hoc signs the app so it launches on Apple
  Silicon, but ad-hoc is not a Developer ID: macOS Gatekeeper and Windows
  SmartScreen still warn on a *downloaded* copy. Two ways past that, and only one
  of them costs money:

  | Path                                  | Cost     | What the user sees     |
  | ------------------------------------- | -------- | ---------------------- |
  | Homebrew cask, `--no-quarantine`      | free     | nothing, it just opens |
  | Apple Developer ID + notarization     | $99/year | nothing, it just opens |
  | Direct `.dmg` download, ad-hoc signed | free     | one warning to clear   |

  For the direct download the recipient clears the warning once. On recent macOS
  the right-click → Open trick is often gone; use System Settings → Privacy &
  Security → "Open Anyway", or run
  `xattr -dr com.apple.quarantine /Applications/DocSigner.app`.

  Windows has its own free path (SignPath Foundation), not set up yet:
  [`../docs/roadmap.md`](../docs/roadmap.md) D7.
- **Token driver.** The DSC vendor's PKCS#11 middleware must be installed on the
  user's machine, the same as for the Frappe flow or the browser extension. It is
  hardware middleware and cannot ride inside the app.
- **App icon.** One per OS, all generated from the one logo source
  `assets/icon.svg` by `scripts/make_assets.py`, along with the extension and
  host icons:

  | OS      | File                       | How it gets there                                                 |
  | ------- | -------------------------- | ----------------------------------------------------------------- |
  | macOS   | `packaging/DocSigner.icns` | `BUNDLE()` puts it in the `.app`                                  |
  | Windows | `packaging/DocSigner.ico`  | embedded in the `.exe` by `EXE()`                                 |
  | Linux   | `packaging/DocSigner.png`  | bundled as data; `__main__.py` hands it to `webview.start(icon=)` |

  Linux is the odd one: GTK has nothing to embed an icon in and wants a file at
  runtime, so without that last row the taskbar shows a generic placeholder. It
  is a PNG rather than the SVG because gdk-pixbuf decodes PNG itself, while SVG
  needs the librsvg loader found through the bundle's `loaders.cache`.

  This covers the running window only. A launcher entry in the applications menu
  needs a `.desktop` file, and the portable tarball has no install step to place
  one.

  macOS caches icons hard, so a rebuilt app can still show the old one in Finder
  or the Dock: `killall Dock Finder`, or move the app once, to refresh.

Verify a build by opening it and signing one PDF with the actual token. That pops
the token PIN, which only the token holder can enter.
