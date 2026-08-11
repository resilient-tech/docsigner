"""Regenerate every icon in the repo from the one logo source, assets/icon.svg.

    python3 scripts/make_assets.py

Writes:
    desktop/packaging/DocSigner.icns    macOS app bundle icon
    desktop/frontend/public/icon.svg    desktop window favicon (copy)
    extension/icons/icon{16,48,128}.png browser extension icons
    host-rs/packaging/icon.ico          embedded in the Windows host .exe

macOS only, because the rasteriser is qlmanage and the .icns packer is
iconutil, both built into the OS. The outputs are committed, so nobody has to
run this to build or ship; run it only after editing assets/icon.svg.

The .ico is packed here from stdlib struct rather than through Pillow: an ICO
holding PNG frames is a 6-byte header plus a 16-byte entry per size, which is
less code than justifying an image library in a script that already shells out.
"""

import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "assets" / "icon.svg"

ICNS = REPO / "desktop" / "packaging" / "DocSigner.icns"
FRONTEND_ICON = REPO / "desktop" / "frontend" / "public" / "icon.svg"
EXTENSION_ICONS = REPO / "extension" / "icons"
HOST_ICO = REPO / "host-rs" / "packaging" / "icon.ico"

# Sizes Windows Explorer picks between, smallest first.
ICO_SIZES = (16, 32, 48, 64, 128, 256)
# The .icns sizes macOS asks for, each also at @2x.
ICNS_SIZES = (16, 32, 128, 256, 512)
EXTENSION_SIZES = (16, 48, 128)


def rasterize(work: Path) -> Path:
    """Render the SVG once at 1024 px; every other size is a downscale of it."""
    subprocess.run(
        ["qlmanage", "-t", "-s", "1024", "-o", str(work), str(SOURCE)],
        check=True,
        capture_output=True,
    )
    master = work / f"{SOURCE.name}.png"
    if not master.is_file():
        sys.exit(f"qlmanage did not render {SOURCE}")
    return master


def resize(master: Path, size: int, out: Path) -> Path:
    subprocess.run(
        ["sips", "-z", str(size), str(size), str(master), "--out", str(out)],
        check=True,
        capture_output=True,
    )
    return out


def write_icns(master: Path, work: Path) -> None:
    iconset = work / "DocSigner.iconset"
    iconset.mkdir()
    for size in ICNS_SIZES:
        resize(master, size, iconset / f"icon_{size}x{size}.png")
        resize(master, size * 2, iconset / f"icon_{size}x{size}@2x.png")
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)],
        check=True,
        capture_output=True,
    )
    print("wrote", ICNS.relative_to(REPO))


def write_extension_icons(master: Path) -> None:
    for size in EXTENSION_SIZES:
        out = EXTENSION_ICONS / f"icon{size}.png"
        resize(master, size, out)
        print("wrote", out.relative_to(REPO))


def write_ico(master: Path, work: Path) -> None:
    frames = [resize(master, size, work / f"ico{size}.png").read_bytes() for size in ICO_SIZES]

    # ICONDIR: reserved, type 1 (icon), image count.
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries, body = b"", b""
    for size, png in zip(ICO_SIZES, frames):
        # 256 is stored as 0; the field is a single byte.
        entries += struct.pack(
            "<BBBBHHII",
            size % 256,  # width
            size % 256,  # height
            0,  # palette colours: 0 for a PNG frame
            0,  # reserved
            1,  # colour planes
            32,  # bits per pixel
            len(png),
            offset,
        )
        body += png
        offset += len(png)

    HOST_ICO.parent.mkdir(parents=True, exist_ok=True)
    HOST_ICO.write_bytes(header + entries + body)
    print("wrote", HOST_ICO.relative_to(REPO))


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("macOS only: this needs qlmanage, sips and iconutil.")
    if not SOURCE.is_file():
        sys.exit(f"missing logo source: {SOURCE}")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        master = rasterize(work)
        write_icns(master, work)
        write_extension_icons(master)
        write_ico(master, work)

    FRONTEND_ICON.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE, FRONTEND_ICON)
    print("wrote", FRONTEND_ICON.relative_to(REPO))


if __name__ == "__main__":
    main()
