# PyInstaller build for the DocSigner desktop app (FastAPI + pywebview).
#
#   cd desktop/frontend && pnpm build      # the window loads frontend/dist
#   cd desktop/backend  && ./.venv/bin/pyinstaller packaging/docsigner-desktop.spec
#   -> desktop/backend/dist/DocSigner.app
#
# (build-macos.sh does all of this.) Still needs a per-OS run to confirm, and a
# real-token sign, the same way the host binary is verified before release.
#
# Handled here:
#   - Token path: the host binary rides along as a sidecar and host.py finds
#     it beside the executable. Still a fresh process per call, which is what
#     keeps the token drivers from wedging.
#   - Trust anchors: repo trust/ is bundled and config.py reads it from _MEIPASS.
#   - Signing libs (pyHanko, pypdfium2, cryptography, …) collected.
#   - macOS: emits a double-clickable .app via BUNDLE().
#
# Still per-OS / manual:
#   - pywebview's GUI backend (pyobjc on macOS) — add hiddenimports if missing.
#   - Code signing + notarization for distribution (Developer ID; otherwise
#     Gatekeeper warns). Sign the .app after this build.

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# This spec lives in desktop/packaging/, so SPECPATH is that folder.
DESKTOP = os.path.abspath(os.path.join(SPECPATH, ".."))
BACKEND = os.path.join(DESKTOP, "backend")
REPO = os.path.abspath(os.path.join(DESKTOP, ".."))
FRONTEND_DIST = os.path.join(DESKTOP, "frontend", "dist")
TRUST = os.path.join(REPO, "trust")
# Not docsigner_desktop/__main__.py directly: PyInstaller runs the entry as a
# top-level script with no package, which breaks that file's relative imports.
# run_desktop.py starts through the package instead.
entry = os.path.join(BACKEND, "run_desktop.py")
ICON = os.path.join(SPECPATH, "DocSigner.icns")

# One version for the whole repo, and host/Cargo.toml is where it lives: the
# release workflow already refuses to publish when the tag disagrees with it.
# Hardcoding it here had it drifting to 0.1.0 while everything else said 0.2.0,
# and a bundle reporting a version nobody can find is what support asks for
# first. The Homebrew cask's `version` has to match this too.
with open(os.path.join(REPO, "host", "Cargo.toml")) as fh:
    VERSION = next(
        line.split('"')[1] for line in fh if line.startswith("version")
    )

# docsigner_core is installed editable (PEP 660), which PyInstaller's static
# analysis can't follow. Point pathex at its source so it resolves as an
# ordinary package.
CORE = os.path.join(REPO, "core")

# The token host is a separate Rust binary, ~1 MB, carried as a sidecar.
# host.py looks for it in _MEIPASS and beside the executable, in that order.
HOST_BINARY_NAME = "docsigner-host.exe" if sys.platform == "win32" else "docsigner-host"

# On macOS this must be the x86_64 build, never the build machine's native one.
# The sidecar is the only process here that loads a PKCS#11 module, and an
# arm64 process cannot load an x86_64-only driver, which some Indian CA
# middleware still ships. Rosetta runs the x86_64 one everywhere. The argument
# in full is at the top of .github/workflows/release.yml; build-macos.sh builds
# this target and checks the result with `file`.
if sys.platform == "darwin":
    HOST_TARGET = "x86_64-apple-darwin"
    HOST_BINARY = os.path.join(REPO, "host", "target", HOST_TARGET, "release", HOST_BINARY_NAME)
    BUILD_HINT = "cargo build --release --target %s --manifest-path host/Cargo.toml" % HOST_TARGET
else:
    HOST_BINARY = os.path.join(REPO, "host", "target", "release", HOST_BINARY_NAME)
    BUILD_HINT = "cargo build --release --manifest-path host/Cargo.toml"

if not os.path.isfile(HOST_BINARY):
    raise SystemExit(
        "the host binary is missing: %s\nBuild it first:  %s" % (HOST_BINARY, BUILD_HINT)
    )

datas = [(FRONTEND_DIST, os.path.join("frontend", "dist"))]
if os.path.isdir(TRUST):
    datas += [(TRUST, "trust")]

# Apache-2.0 wants both shipped with the app, not only in the repo, and the
# host's release archive carries them for the same reason. The bundled
# dependencies' own notices ride along inside their collected packages, which
# collect_all() below already picks up.
datas += [(os.path.join(REPO, name), ".") for name in ("LICENSE", "NOTICE")]

# "." puts it at the bundle root, where _MEIPASS points.
binaries = [(HOST_BINARY, ".")]
hiddenimports = collect_submodules("uvicorn")

# Everything the signing path and the window need, with their data files and
# native libs. Wrapped so an absent optional package doesn't break the build.
#
# No python-pkcs11 and no signer_host: talking to the token is the Rust
# binary's job now, and nothing in this process loads a PKCS#11 module.
for pkg in (
    "webview", "pyhanko", "pyhanko_certvalidator", "asn1crypto", "cryptography",
    "pypdfium2", "pypdfium2_raw", "qrcode", "PIL", "oscrypto",
    "docsigner_core",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# Weight this app never uses. collect_all() above hands PyInstaller explicit
# binary lists, which `excludes` does not filter, so drop them by name here.
#
#   lxml            only docsigner_core.xades imports it, and this app signs PDFs.
#                   Verified: no lxml module loads across docsigner_core's signing,
#                   validation, rendering, LTV and PDF/A paths, or pyHanko's
#                   signers and validation.
#   PIL codecs      _avif, _webp and _imagingcms are separate extension modules
#                   with their own dylibs. The core _imaging.so links tiff,
#                   jpeg, openjp2, z and xcb, so those have to stay; freetype
#                   and harfbuzz stay too, they draw the handwritten stamp.
_DEAD_WEIGHT = (
    "lxml",
    "PIL/_avif", "PIL/_webp", "PIL/_imagingcms",
    "libavif", "libsharpyuv", "libwebp", "liblcms2",
)

# Two bigger cuts were measured and rejected, so nobody re-derives them:
#
#   pdf.js for the preview, dropping pypdfium2 (6.5 MB). It does not come off:
#   signing.py calls docsigner_core.page_size() per file to turn the fractional
#   placement into PDF points, and that is pypdfium2. Adding pdf.js would put
#   ~1.5 MB on top for a net loss, and push whole PDFs into the webview where
#   today a ~5-50 KB JPEG crosses. Scanned invoices run 10-50 MB.
#
#   pywebview js_api, dropping FastAPI and uvicorn. Worth ~1 MB, not the ~8 it
#   looks like: those are pure Python and PyInstaller compresses them into the
#   PYZ. Only pydantic_core is real weight (4 MB) and it stays, because
#   hand-rolling validation of signing request bodies is a bad trade. The cost
#   is rewriting app.py, api.ts and the frontend error handling, and losing the
#   --server + `pnpm dev` hot-reload loop permanently.


def _wanted(entry):
    name = entry[0].replace("\\", "/")
    return not any(dead in name for dead in _DEAD_WEIGHT)


datas = [d for d in datas if _wanted(d)]
binaries = [b for b in binaries if _wanted(b)]
hiddenimports = [h for h in hiddenimports if not h.startswith("lxml")]

excludes = ["lxml", "PIL._avif", "PIL._webp", "PIL._imagingcms"]

# requirements.txt asks for plain uvicorn, but a venv built before that change
# still has the [standard] extras. uvicorn falls back to asyncio and h11 when
# they are missing, so exclude them here and the trim holds either way.
excludes += ["uvloop", "watchfiles", "httptools", "websockets"]

# tkinter used to be the PIN dialog on Windows and Linux. The Rust host owns
# that on every OS now (osascript, a PowerShell WinForms box, zenity/kdialog/
# pinentry), so nothing in this process opens a Tk window. Worth ~7.7 MB with
# the tcl and tk data directories.
excludes += ["tkinter", "PIL.ImageTk", "PIL._imagingtk"]

a = Analysis(
    [entry],
    pathex=[BACKEND, CORE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="docsigner-desktop",
    debug=False,
    strip=True,
    upx=False,
    console=False,  # GUI app; pywebview owns the window
)

# strip: symbols only, and build-macos.sh signs after this, so the signature is
# applied to the stripped binaries. upx stays off: it breaks macOS code signing
# and trips Windows antivirus.
coll = COLLECT(exe, a.binaries, a.datas, strip=True, upx=False, name="docsigner-desktop")

app = BUNDLE(
    coll,
    name="DocSigner.app",
    icon=ICON if os.path.exists(ICON) else None,
    bundle_identifier="tech.resilient.docsigner",
    info_plist={
        "CFBundleName": "DocSigner",
        "CFBundleDisplayName": "DocSigner",
        "CFBundleShortVersionString": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # The window loads http://127.0.0.1:<port>; allow local networking.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
