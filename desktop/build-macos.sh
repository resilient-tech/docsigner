#!/usr/bin/env bash
# Build DocSigner for macOS as a self-contained .app and .dmg. No Python or
# venv is needed on the machine that installs it. Run from the desktop/ folder:
#   ./build-macos.sh
# Output: backend/dist/DocSigner.app  and  backend/dist/DocSigner.dmg
#
# ---------------------------------------------------------------------------
# Everything here is built x86_64, on purpose, even on an Apple Silicon Mac.
#
# The sidecar host has to be x86_64: it is the only process that loads a
# PKCS#11 driver, and an arm64 process cannot load an x86_64-only module, which
# some Indian CA middleware still ships. The full argument is at the top of
# .github/workflows/release.yml.
#
# Given that, the .app is x86_64 too. Rosetta is already required on Apple
# Silicon for the sidecar, so matching it costs the user nothing new and keeps
# the app running on Intel Macs, which an arm64 build would drop. One download
# per OS, no architecture for anyone to choose.
#
# PyInstaller cannot cross-compile: it bundles whatever the interpreter running
# it is. So this needs an x86_64 (or universal) CPython 3.12, driven through
# Rosetta. Every arch is verified with `file` before the .dmg is cut, because
# the first version of this script had no such check and quietly shipped an
# arm64 build for a month.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

REPO="$(cd .. && pwd)"
HOST_TARGET="x86_64-apple-darwin"

# --- the x86_64 interpreter -------------------------------------------------
# DOCSIGNER_PYTHON wins, so a python.org universal2 install or any other 3.12
# can be used. Otherwise ask uv, which is how this is set up on the dev Mac.
PYTHON="${DOCSIGNER_PYTHON:-}"
if [ -z "$PYTHON" ]; then
    PYTHON="$(uv python find cpython-3.12-macos-x86_64 2>/dev/null || true)"
fi
if [ -z "$PYTHON" ] || ! file -b "$PYTHON" | grep -q 'x86_64'; then
    cat >&2 <<'EOF'
error: need an x86_64 CPython 3.12 to build this app (see the header comment).

Install one:
    uv python install cpython-3.12-macos-x86_64

That download is ~24 MB from GitHub and uv gives up after 30 seconds, which
on a slow link looks like a broken command rather than a timeout:
    UV_HTTP_TIMEOUT=900 uv python install cpython-3.12-macos-x86_64

Or point at your own, such as a python.org universal2 install:
    DOCSIGNER_PYTHON=/path/to/python3.12 ./build-macos.sh
EOF
    exit 1
fi
echo "==> Interpreter: $PYTHON ($(file -b "$PYTHON" | cut -d, -f1))"

echo "==> Building the sidecar host ($HOST_TARGET)"
# The spec looks for the binary under this exact target directory, so building
# it here is what keeps the two in step.
if ! command -v cargo >/dev/null; then
    echo "error: cargo not found; install Rust from https://rustup.rs" >&2
    exit 1
fi
rustup target add "$HOST_TARGET" >/dev/null 2>&1 || true
cargo build --release --target "$HOST_TARGET" --manifest-path "$REPO/host/Cargo.toml"

echo "==> Building frontend"
( cd frontend && pnpm install && pnpm build )

echo "==> Setting up backend venv"
cd backend
# A venv built by the wrong interpreter is how the arm64 build happened, and
# the arch is baked in at creation. The venv is disposable scaffolding, so
# rebuild it rather than asking.
if [ -d .venv ] && ! file -b .venv/bin/python3 | grep -q 'x86_64'; then
    echo "    existing venv is not x86_64, rebuilding it"
    rm -rf .venv
fi
[ -d .venv ] || arch -x86_64 "$PYTHON" -m venv .venv
# arch -x86_64 on every call: a universal2 venv python would otherwise run its
# arm64 slice and pull arm64 wheels. Always `python -m`, never the pip or
# pyinstaller console script: arch sets the preferred architecture on the image
# it execs, and for a shebang script that image is the script, not the
# interpreter the kernel then picks. Naming the interpreter is what makes the
# preference land where it matters.
arch -x86_64 ./.venv/bin/python -m pip install -q -r requirements.txt
arch -x86_64 ./.venv/bin/python -m pip install -q pyinstaller

echo "==> Packaging .app"
# Spec lives in desktop/packaging/; we are in desktop/backend/. PyInstaller
# writes dist/ and build/ to the current dir, so dist lands in backend/.
# Wiped first so a rename or a failed run cannot leave an old .app behind for
# the .dmg step to pick up.
rm -rf dist build
arch -x86_64 ./.venv/bin/python -m PyInstaller --noconfirm ../packaging/docsigner-desktop.spec

echo "==> Verifying architecture"
# PyInstaller 6 puts binaries in Contents/Frameworks and symlinks them into
# Contents/MacOS, so -type f finds the real file either way.
APP_BINARY="dist/DocSigner.app/Contents/MacOS/docsigner-desktop"
SIDECAR="$(find dist/DocSigner.app -name docsigner-host -type f | head -1)"
if [ -z "$SIDECAR" ]; then
    echo "error: the sidecar host is not in the bundle" >&2
    exit 1
fi
for binary in "$APP_BINARY" "$SIDECAR"; do
    echo "    $(file -b "$binary" | cut -d, -f1)  $binary"
    file -b "$binary" | grep -q 'x86_64' || {
        echo "error: $binary is not x86_64; see the header comment" >&2
        exit 1
    }
done

echo "==> Ad-hoc signing"
# Apple Silicon refuses to launch a bundle without a valid signature. Ad-hoc
# (-s -) is enough to run locally, and enough for the Homebrew cask installed
# with --no-quarantine. A Developer ID is only needed for a bare .dmg download.
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
echo "    Ad-hoc signed, so a bare download warns once. The cask does not."

# The cask pins the .dmg by checksum, and getting it from here beats computing
# it by hand at release time. shasum ships with macOS.
echo
echo "==> Update packaging/homebrew/docsigner.rb with:"
echo "    sha256 \"$(shasum -a 256 dist/DocSigner.dmg | cut -d' ' -f1)\""
