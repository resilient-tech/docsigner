# PyInstaller build for the OpenSigner desktop app (FastAPI + pywebview).
#
#   cd desktop/frontend && pnpm build      # the window loads frontend/dist
#   cd desktop/backend  && ./.venv/bin/pyinstaller packaging/opensigner-desktop.spec
#   -> desktop/backend/dist/OpenSigner.app
#
# (build-macos.sh does all of this.) Still needs a per-OS run to confirm, and a
# real-token sign, the same way the host binary is verified before release.
#
# Handled here:
#   - Token path: host.py re-execs the frozen app as `--host-cli`, so signing
#     still happens in a fresh process (no `python -m` needed). __main__ routes it.
#   - Trust anchors: repo trust/ is bundled and config.py reads it from _MEIPASS.
#   - Signing libs (pyHanko, pypdfium2, cryptography, python-pkcs11, …) collected.
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
# Not opensigner_desktop/__main__.py directly: PyInstaller runs the entry as a
# top-level script with no package, which breaks that file's relative imports.
# run_desktop.py starts through the package instead.
entry = os.path.join(BACKEND, "run_desktop.py")
ICON = os.path.join(SPECPATH, "OpenSigner.icns")

# signer_core / signer_host are installed editable (PEP 660), which PyInstaller's
# static analysis can't follow. Point pathex at their source so they resolve as
# ordinary packages.
CORE = os.path.join(REPO, "core")
HOST = os.path.join(REPO, "host")

datas = [(FRONTEND_DIST, os.path.join("frontend", "dist"))]
if os.path.isdir(TRUST):
    datas += [(TRUST, "trust")]

binaries = []
hiddenimports = collect_submodules("uvicorn")

# Everything the signing path and the window need, with their data files and
# native libs. Wrapped so an absent optional package doesn't break the build.
for pkg in (
    "webview", "pyhanko", "pyhanko_certvalidator", "asn1crypto", "cryptography",
    "pypdfium2", "pypdfium2_raw", "qrcode", "PIL", "pkcs11", "oscrypto",
    "signer_core", "signer_host",
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
#   lxml            only signer_core.xades imports it, and this app signs PDFs.
#                   Verified: no lxml module loads across signer_core's signing,
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

# ponytail: tkinter is the PIN dialog on Windows and Linux (host pin.py falls
# back to it when the caller supplies no PIN); macOS uses osascript, so it is
# dead weight there only. Drop the platform check once the Rust host owns the
# dialog on every OS, and this becomes unconditional.
if sys.platform == "darwin":
    excludes += ["tkinter", "PIL.ImageTk", "PIL._imagingtk"]

a = Analysis(
    [entry],
    pathex=[BACKEND, CORE, HOST],
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
    name="opensigner-desktop",
    debug=False,
    strip=True,
    upx=False,
    console=False,  # GUI app; pywebview owns the window
)

# strip: symbols only, and build-macos.sh signs after this, so the signature is
# applied to the stripped binaries. upx stays off: it breaks macOS code signing
# and trips Windows antivirus.
coll = COLLECT(exe, a.binaries, a.datas, strip=True, upx=False, name="opensigner-desktop")

app = BUNDLE(
    coll,
    name="OpenSigner.app",
    icon=ICON if os.path.exists(ICON) else None,
    bundle_identifier="tech.resilient.opensigner",
    info_plist={
        "CFBundleName": "OpenSigner",
        "CFBundleDisplayName": "OpenSigner",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # The window loads http://127.0.0.1:<port>; allow local networking.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
