"""Regenerate every icon in the repo from the one logo source, assets/icon.svg.

    python3 scripts/make_assets.py

Writes:
    desktop/packaging/DocSigner.icns    macOS app bundle icon (macOS only)
    desktop/frontend/public/icon.svg    desktop window favicon (copy)
    extension/icons/icon{16,48,128}.png browser extension icons
    host-rs/packaging/icon.ico          embedded in the Windows host .exe

The outputs are committed, so building and shipping never needs this. Run it
after editing assets/icon.svg.

Rasterising goes through headless Chromium (Chrome, Chromium, Edge or Brave,
whichever is installed; DOCSIGNER_CHROMIUM overrides the search). macOS ships
qlmanage, which looks like the obvious choice and is the wrong one: it flattens
onto white, so every icon came out with opaque white corners where the squircle
does not reach. Chromium keeps the alpha, and it is the same engine that draws
the SVG favicon, so what renders here is what users see. Each size is rendered
from the vector rather than downscaled from one big raster, which keeps the
mark's strokes crisp at 16 px.

Packing the .ico is done here from struct: an ICO holding PNG frames is a
6-byte header plus a 16-byte entry per size, which is less code than justifying
an image library. Packing the .icns needs iconutil, so that one output is macOS
only; the rest regenerate anywhere.
"""

import os
import re
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

CHROMIUM_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "brave-browser",
)


def find_chromium() -> str:
    override = os.environ.get("DOCSIGNER_CHROMIUM")
    if override:
        return override
    for candidate in CHROMIUM_CANDIDATES:
        found = candidate if os.access(candidate, os.X_OK) else shutil.which(candidate)
        if found:
            return found
    sys.exit(
        "no Chromium-based browser found to rasterise the SVG.\n"
        "Install Chrome, or point DOCSIGNER_CHROMIUM at a browser binary."
    )


def render(browser: str, svg: Path, size: int, out: Path) -> Path:
    """Rasterise one SVG at one size, transparent outside the artwork."""
    # An <img> at an explicit size, in a page with no margin and no background,
    # so the screenshot is exactly the artwork and nothing else.
    page = svg.with_name(f"{svg.stem}-{size}.html")
    page.write_text(
        "<style>html,body{margin:0;padding:0;background:transparent}"
        f'img{{display:block}}</style><img src="{svg.name}" width="{size}" height="{size}">'
    )
    subprocess.run(
        [
            browser,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--default-background-color=00000000",
            f"--window-size={size},{size}",
            f"--screenshot={out}",
            page.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    if not out.is_file():
        sys.exit(f"{browser} did not render {svg} at {size} px")
    return out


def inset_for_macos(work: Path) -> Path:
    """A copy of the logo with the margin macOS dock icons are drawn inside.

    Apple's grid gives a rounded-rect app icon 824 of the 1024 px canvas and
    leaves the rest transparent; a full-bleed icon reads as oversized next to
    every other app. Widening the viewBox is the whole change, so the artwork
    stays in one file instead of a second copy drifting out of sync.
    """
    margin = round(1024 * (1024 / 824 - 1) / 2)
    side = 1024 + 2 * margin

    inset, count = re.subn(
        r'viewBox="0 0 1024 1024"',
        f'viewBox="{-margin} {-margin} {side} {side}"',
        SOURCE.read_text(),
        count=1,
    )
    if count != 1:
        sys.exit(f"{SOURCE} no longer has the viewBox this rewrite expects")

    out = work / "icon-macos.svg"
    out.write_text(inset)
    return out


def write_icns(browser: str, work: Path) -> None:
    if sys.platform != "darwin":
        print("skipped", ICNS.relative_to(REPO), "(needs iconutil, macOS only)")
        return

    svg = inset_for_macos(work)
    iconset = work / "DocSigner.iconset"
    iconset.mkdir()
    for size in ICNS_SIZES:
        render(browser, svg, size, iconset / f"icon_{size}x{size}.png")
        render(browser, svg, size * 2, iconset / f"icon_{size}x{size}@2x.png")
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)],
        check=True,
        capture_output=True,
    )
    print("wrote", ICNS.relative_to(REPO))


def write_extension_icons(browser: str, svg: Path) -> None:
    for size in EXTENSION_SIZES:
        out = EXTENSION_ICONS / f"icon{size}.png"
        render(browser, svg, size, out)
        print("wrote", out.relative_to(REPO))


def write_ico(browser: str, svg: Path, work: Path) -> None:
    frames = [render(browser, svg, size, work / f"ico{size}.png").read_bytes() for size in ICO_SIZES]

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
    if not SOURCE.is_file():
        sys.exit(f"missing logo source: {SOURCE}")
    browser = find_chromium()

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # The renderer loads the SVG over file://, so it has to sit beside the
        # generated wrapper pages.
        svg = work / SOURCE.name
        shutil.copyfile(SOURCE, svg)

        write_icns(browser, work)
        write_extension_icons(browser, svg)
        write_ico(browser, svg, work)

    FRONTEND_ICON.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE, FRONTEND_ICON)
    print("wrote", FRONTEND_ICON.relative_to(REPO))


if __name__ == "__main__":
    main()
