#!/usr/bin/env bash
# Build OpenSigner for macOS as a self-contained .app and .dmg. No Python or
# venv is needed on the machine that installs it. Run from the desktop/ folder:
#   ./build-macos.sh
# Output: backend/dist/OpenSigner.app  and  backend/dist/OpenSigner.dmg
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Building frontend"
( cd frontend && pnpm install && pnpm build )

echo "==> Setting up backend venv"
cd backend
[ -d .venv ] || python3.12 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt
./.venv/bin/pip install -q pyinstaller

echo "==> Packaging .app"
# Spec lives in desktop/packaging/; we are in desktop/backend/. PyInstaller
# writes dist/ and build/ to the current dir, so dist lands in backend/.
./.venv/bin/pyinstaller --noconfirm ../packaging/opensigner-desktop.spec

echo "==> Ad-hoc signing"
# Apple Silicon refuses to launch a bundle without a valid signature. Ad-hoc
# (-s -) is enough to run locally; use a Developer ID here to distribute.
codesign --force --deep --sign - dist/OpenSigner.app

echo "==> Packaging .dmg (drag-to-Applications installer)"
# hdiutil ships with macOS, so no extra dependency. Stage the .app next to an
# Applications symlink so the mounted disk shows the usual drag target.
STAGE="$(mktemp -d)"
cp -R dist/OpenSigner.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f dist/OpenSigner.dmg
hdiutil create -volname OpenSigner -srcfolder "$STAGE" -ov -format UDZO dist/OpenSigner.dmg
rm -rf "$STAGE"

echo "==> Done:"
echo "    backend/dist/OpenSigner.app   (run: open dist/OpenSigner.app)"
echo "    backend/dist/OpenSigner.dmg   (hand this to users)"
echo "    Unsigned, so first launch: right-click > Open (or clear Gatekeeper)."
