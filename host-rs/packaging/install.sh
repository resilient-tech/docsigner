#!/bin/sh
# Install the DocSigner native messaging host on macOS or Linux.
#
# Usage:
#     ./install.sh [CHROME_EXTENSION_ID] [FIREFOX_EXTENSION_ID]
#
# Run as a normal user for a per-user install (~/.local/docsigner), or as
# root for a system-wide install (/usr/local/docsigner).
#
# Build the binary first:  cargo build --release
# Or point DOCSIGNER_BINARY at an existing build.

set -eu

CHROME_EXT_ID="${1:-__EXTENSION_ID__}"
FIREFOX_EXT_ID="${2:-__EXTENSION_ID__}"
HOST_NAME="com.docsigner.host"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ "$CHROME_EXT_ID" = "__EXTENSION_ID__" ]; then
    echo "warning: no extension ID given; manifests keep the __EXTENSION_ID__ placeholder." >&2
    echo "         Rerun with the real ID once the extension is installed." >&2
fi

# Locate the binary.
#
# "$HERE/.." first, which is where it sits in a downloaded release archive:
# most people run this from an unpacked download, not a checkout. Then a cargo
# build, release before debug so a stale debug build is never the one that gets
# registered.
BINARY="${DOCSIGNER_BINARY:-}"
if [ -z "$BINARY" ]; then
    for candidate in \
        "$HERE/../docsigner-host" \
        "$HERE/../target/release/docsigner-host" \
        "$HERE/../target/debug/docsigner-host" \
        "$HERE/docsigner-host"; do
        if [ -f "$candidate" ]; then
            BINARY="$candidate"
            break
        fi
    done
fi
if [ -z "$BINARY" ] || [ ! -f "$BINARY" ]; then
    echo "error: docsigner-host binary not found next to this script." >&2
    echo "       From a downloaded release: run this from the unpacked folder." >&2
    echo "       From a checkout:           cargo build --release" >&2
    echo "       Or set DOCSIGNER_BINARY to its path." >&2
    exit 1
fi

if [ "$(id -u)" = "0" ]; then
    INSTALL_DIR="/usr/local/docsigner"
    SYSTEM_INSTALL=1
else
    INSTALL_DIR="$HOME/.local/docsigner"
    SYSTEM_INSTALL=0
fi

mkdir -p "$INSTALL_DIR"
cp "$BINARY" "$INSTALL_DIR/docsigner-host"
chmod 755 "$INSTALL_DIR/docsigner-host"
echo "installed binary: $INSTALL_DIR/docsigner-host"

write_manifest() {
    # $1 = template (chrome|firefox), $2 = extension id, $3 = target directory
    mkdir -p "$3"
    sed -e "s|__HOST_PATH__|$INSTALL_DIR/docsigner-host|" \
        -e "s|__EXTENSION_ID__|$2|" \
        "$HERE/manifests/$HOST_NAME.$1.json" > "$3/$HOST_NAME.json"
    echo "wrote manifest:   $3/$HOST_NAME.json"
}

OS="$(uname -s)"

if [ "$OS" = "Darwin" ]; then
    if [ "$SYSTEM_INSTALL" = "1" ]; then
        write_manifest chrome  "$CHROME_EXT_ID"  "/Library/Google/Chrome/NativeMessagingHosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "/Library/Application Support/Chromium/NativeMessagingHosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "/Library/Microsoft/Edge/NativeMessagingHosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts"
        write_manifest firefox "$FIREFOX_EXT_ID" "/Library/Application Support/Mozilla/NativeMessagingHosts"
    else
        APP_SUPPORT="$HOME/Library/Application Support"
        write_manifest chrome  "$CHROME_EXT_ID"  "$APP_SUPPORT/Google/Chrome/NativeMessagingHosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "$APP_SUPPORT/Chromium/NativeMessagingHosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "$APP_SUPPORT/Microsoft Edge/NativeMessagingHosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "$APP_SUPPORT/BraveSoftware/Brave-Browser/NativeMessagingHosts"
        write_manifest firefox "$FIREFOX_EXT_ID" "$APP_SUPPORT/Mozilla/NativeMessagingHosts"
    fi
else
    if [ "$SYSTEM_INSTALL" = "1" ]; then
        write_manifest chrome  "$CHROME_EXT_ID"  "/etc/opt/chrome/native-messaging-hosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "/etc/chromium/native-messaging-hosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "/etc/opt/edge/native-messaging-hosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "/etc/opt/brave/native-messaging-hosts"
        write_manifest firefox "$FIREFOX_EXT_ID" "/usr/lib/mozilla/native-messaging-hosts"
    else
        write_manifest chrome  "$CHROME_EXT_ID"  "$HOME/.config/google-chrome/NativeMessagingHosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "$HOME/.config/chromium/NativeMessagingHosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "$HOME/.config/microsoft-edge/NativeMessagingHosts"
        write_manifest chrome  "$CHROME_EXT_ID"  "$HOME/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts"
        write_manifest firefox "$FIREFOX_EXT_ID" "$HOME/.mozilla/native-messaging-hosts"
    fi
fi

echo "done."
