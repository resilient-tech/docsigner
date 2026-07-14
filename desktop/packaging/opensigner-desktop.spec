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

a = Analysis(
    [entry],
    pathex=[BACKEND, CORE, HOST],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="opensigner-desktop",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # GUI app; pywebview owns the window
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="opensigner-desktop")

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
