# PyInstaller build for the OpenSigner desktop app (FastAPI + pywebview).
#
# STARTING POINT, not yet verified end to end. Build and test per OS before
# release, the same way the host binary is (real-token runs are a manual step):
#     cd desktop/frontend && pnpm build      # the window loads frontend/dist
#     cd desktop/backend  && pyinstaller packaging/opensigner-desktop.spec
#
# Known open items (each needs a real per-OS run):
#   1. Token path. host.py runs the signing host as `python -m signer_host.cli`,
#      which does not exist in a frozen bundle. Decide between bundling the
#      opensigner-host binary as a sidecar (keeps the fresh-subprocess design)
#      or signing in-process, then wire it in and test with a token. See host.py.
#   2. Trust anchors. config.py autodetects the repo trust/ by path, which the
#      frozen app cannot see. Bundle trust/ (add to datas) and point
#      OPENSIGNER_TRUST_DIR at it, or LTV profiles will be unavailable (B-B works).
#   3. Platform GUI deps. pywebview pulls a per-OS backend (pyobjc on macOS,
#      pythonnet/Edge WebView2 on Windows, GTK/Qt on Linux); add hiddenimports
#      if collect_all("webview") misses them on your target.
#   4. macOS: wrap in BUNDLE() for a double-clickable .app; this spec emits a
#      plain onefile executable.

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

BACKEND = os.path.join(SPECPATH, "..")
FRONTEND_DIST = os.path.join(BACKEND, "..", "frontend", "dist")
entry = os.path.join(BACKEND, "opensigner_desktop", "__main__.py")

datas = [(FRONTEND_DIST, os.path.join("frontend", "dist"))]
datas += collect_data_files("signer_core")  # stamp fonts + package data

hiddenimports = collect_submodules("uvicorn")
webview_datas, webview_binaries, webview_hidden = collect_all("webview")
datas += webview_datas
hiddenimports += webview_hidden

a = Analysis(
    [entry],
    pathex=[BACKEND],
    binaries=webview_binaries,
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
    a.binaries,
    a.datas,
    name="opensigner-desktop",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # GUI app; pywebview owns the window
    disable_windowed_traceback=False,
)
