"""Which platforms get a window icon handed over at runtime.

GTK needs a file, and Cocoa uses one as the dock image. Windows needs the .ico:
WinForms throws `Argument 'picture' must be a picture that can be used as a Icon`
on a .png and the window never opens.

These tests keep each platform on the file it can read. Windows was handed the .png
once and would not start; the fix after that excluded macOS too, which needlessly
cost it the dock image.

Skipped where the desktop backend's own dependencies are not installed, which is
how the python CI job runs.
"""

import struct
import sys
from pathlib import Path

import pytest

entry = pytest.importorskip(
    "docsigner_desktop.__main__", reason="needs the desktop backend's dependencies"
)

ICO = Path(__file__).resolve().parents[3] / "desktop" / "packaging" / "DocSigner.ico"

# What Windows asks a window for, and at which display scaling. A size that is not
# in the file gets stretched from the nearest one that is, which is what made the
# title bar blurry at 125%.
TITLE_BAR_SIZES = {16: "100%", 20: "125%", 24: "150%", 32: "200%", 40: "125% large"}


def test_windows_gets_the_ico(monkeypatch):
    """Never the .png: WinForms throws on it rather than ignoring it."""
    monkeypatch.setattr(sys, "platform", "win32")
    icon = entry._icon()
    assert icon and icon.endswith("DocSigner.ico")


def _ico_frames() -> dict[int, tuple[int, int]]:
    """Each frame's declared size, and the size its image really is."""
    data = ICO.read_bytes()
    _, _, count = struct.unpack("<HHH", data[:6])
    frames = {}
    for i in range(count):
        width, _, _, _, _, _, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i : 22 + 16 * i])
        png = data[offset : offset + length]
        frames[width or 256] = struct.unpack(">II", png[16:24])
    return frames


@pytest.mark.parametrize("size,scaling", TITLE_BAR_SIZES.items(), ids=str)
def test_the_ico_carries_every_size_windows_asks_for(size, scaling):
    frames = _ico_frames()
    assert size in frames, (
        f"no {size} px frame, the one Windows wants at {scaling} scaling — it will "
        "stretch the nearest instead. Add it to ICO_SIZES in scripts/make_assets.py."
    )
    assert frames[size] == (size, size), f"the {size} px frame really holds {frames[size]}"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_gtk_and_cocoa_get_the_png(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    icon = entry._icon()
    assert icon and icon.endswith("DocSigner.png"), (
        f"{platform} lost its icon: either the gate widened or "
        "desktop/packaging/DocSigner.png is gone (scripts/make_assets.py writes it)"
    )
