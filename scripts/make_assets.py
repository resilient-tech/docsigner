"""Regenerate every icon in the repo from the one logo source, assets/icon.svg.

    python3 scripts/make_assets.py

Writes:
    desktop/packaging/DocSigner.icns    macOS app bundle icon (macOS only)
    desktop/packaging/DocSigner.ico     embedded in the Windows desktop .exe
    desktop/packaging/DocSigner.png     GTK window and taskbar icon on Linux
    desktop/frontend/public/icon.svg    desktop window favicon (copy)
    extension/icons/icon{16,48,128}.png browser extension icons
    host/packaging/icon.ico             embedded in the Windows host .exe

The outputs are committed, so building and shipping never needs this. Run it
after editing assets/icon.svg.

Drawing goes through headless Chrome. macOS ships qlmanage, which looks like
the obvious tool and is the wrong one: it paints onto white, so every icon came
out with white corners. Chrome keeps the transparency, and it is the same engine
that draws the favicon, so what we make here is what people see.

Every size is drawn from the vector, never shrunk from one big image, so the
mark stays sharp at 16 px.

The .ico is packed by hand: it is a 6-byte header plus 16 bytes per size, which
is less code than justifying a new dependency. The .icns needs a macOS tool, so
that one output is macOS only.
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
# One .ico per Windows binary, each beside the packaging that embeds it.
HOST_ICO = REPO / "host" / "packaging" / "icon.ico"
DESKTOP_ICO = REPO / "desktop" / "packaging" / "DocSigner.ico"
# Linux has nothing to embed an icon in, so GTK is handed this file at runtime.
# PNG, not the SVG: gdk-pixbuf decodes PNG itself, while SVG needs the librsvg
# loader to be found through the bundle's loaders.cache.
LINUX_PNG = REPO / "desktop" / "packaging" / "DocSigner.png"
# What GNOME, KDE and Cinnamon ask for at the largest size they draw.
LINUX_PNG_SIZE = 256

# Sizes Windows picks between, smallest first. 20, 24 and 40 are there for the
# scaled displays most laptops ship with: the title bar asks for SM_CXSMICON,
# which is 16 px at 100% but 20 at 125% and 24 at 150%, and Explorer's large icon
# asks for SM_CXICON — 40 at 125%. A size Windows wants and cannot find is
# stretched from the nearest one it can, which is what made the title bar blurry.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
# The .icns sizes macOS asks for, each also at @2x.
ICNS_SIZES = (16, 32, 128, 256, 512)
EXTENSION_SIZES = (16, 48, 128)

CHROMIUM_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    # Windows installs into Program Files and puts nothing on PATH, so the
    # names below never find it and the paths have to be spelled out.
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
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
    """Draw one SVG at one size. Everything outside the art stays see-through."""
    # A bare page with no margin and no background, so the screenshot is the
    # artwork and nothing else.
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

    # Header: reserved, "this is an icon", how many sizes follow.
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries, body = b"", b""
    for size, png in zip(ICO_SIZES, frames):
        # The size field is one byte, so 256 has to be written as 0.
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

    blob = header + entries + body
    for out in (HOST_ICO, DESKTOP_ICO):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(blob)
        print("wrote", out.relative_to(REPO))


def main() -> None:
    if not SOURCE.is_file():
        sys.exit(f"missing logo source: {SOURCE}")
    browser = find_chromium()

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # The browser loads the SVG off disk, so it has to sit beside the
        # generated wrapper pages.
        svg = work / SOURCE.name
        shutil.copyfile(SOURCE, svg)

        write_icns(browser, work)
        write_extension_icons(browser, svg)
        write_ico(browser, svg, work)
        render(browser, svg, LINUX_PNG_SIZE, LINUX_PNG)
        print("wrote", LINUX_PNG.relative_to(REPO))

    FRONTEND_ICON.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE, FRONTEND_ICON)
    print("wrote", FRONTEND_ICON.relative_to(REPO))


if __name__ == "__main__":
    main()
