#!/usr/bin/env bash
# Regenerate OpenSigner.icns from icon.svg (the logo: signature mark on the
# green squircle). macOS-only, using built-in tools: qlmanage rasterises the
# SVG, sips resizes, iconutil packs the .icns. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

qlmanage -t -s 1024 -o "$WORK" icon.svg >/dev/null 2>&1
MASTER="$WORK/icon.svg.png"
[ -f "$MASTER" ] || { echo "qlmanage did not render icon.svg"; exit 1; }

SET="$WORK/OpenSigner.iconset"
mkdir "$SET"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s"           "$MASTER" --out "$SET/icon_${s}x${s}.png"    >/dev/null
  sips -z "$((s*2))" "$((s*2))" "$MASTER" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done

iconutil -c icns "$SET" -o OpenSigner.icns
echo "wrote OpenSigner.icns"
