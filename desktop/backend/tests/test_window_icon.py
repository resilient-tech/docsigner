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

import sys

import pytest

entry = pytest.importorskip(
    "docsigner_desktop.__main__", reason="needs the desktop backend's dependencies"
)


def test_windows_gets_the_ico(monkeypatch):
    """Never the .png: WinForms throws on it rather than ignoring it."""
    monkeypatch.setattr(sys, "platform", "win32")
    icon = entry._icon()
    assert icon and icon.endswith("DocSigner.ico")


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_gtk_and_cocoa_get_the_png(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    icon = entry._icon()
    assert icon and icon.endswith("DocSigner.png"), (
        f"{platform} lost its icon: either the gate widened or "
        "desktop/packaging/DocSigner.png is gone (scripts/make_assets.py writes it)"
    )
