# PyInstaller one-file build for the native messaging host.
#
# From the host/ directory:
#     pyinstaller packaging/opensigner-host.spec
#
# Output: dist/opensigner-host (dist/opensigner-host.exe on Windows).

import os

entry = os.path.join(SPECPATH, "..", "signer_host", "__main__.py")

a = Analysis(
    [entry],
    pathex=[os.path.join(SPECPATH, "..")],
    binaries=[],
    datas=[],
    hiddenimports=["signer_host.main", "signer_host.cli"],
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
    name="opensigner-host",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # stdio carries the protocol; this must stay a console binary
    disable_windowed_traceback=False,
)
