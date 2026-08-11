#!/usr/bin/env bash
# Build DocSigner for macOS as a self-contained .app and .dmg. No Python or
# venv is needed on the machine that installs it. Run from the desktop/ folder:
#   ./build-macos.sh
# Output: backend/dist/DocSigner.app  and  backend/dist/DocSigner.dmg
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
./.venv/bin/pyinstaller --noconfirm ../packaging/docsigner-desktop.spec

echo "==> Ad-hoc signing"
# Apple Silicon refuses to launch a bundle without a valid signature. Ad-hoc
# (-s -) is enough to run locally; use a Developer ID here to distribute.
codesign --force --deep --sign - dist/DocSigner.app

echo "==> Packaging .dmg (drag-to-Applications installer)"
# hdiutil ships with macOS, so no extra dependency. Stage the .app next to an
# Applications symlink so the mounted disk shows the usual drag target.
STAGE="$(mktemp -d)"
cp -R dist/DocSigner.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f dist/DocSigner.dmg
hdiutil create -volname DocSigner -srcfolder "$STAGE" -ov -format UDZO dist/DocSigner.dmg
rm -rf "$STAGE"

echo "==> Done:"
echo "    backend/dist/DocSigner.app   (run: open dist/DocSigner.app)"
echo "    backend/dist/DocSigner.dmg   (hand this to users)"
echo "    Unsigned, so first launch: right-click > Open (or clear Gatekeeper)."
