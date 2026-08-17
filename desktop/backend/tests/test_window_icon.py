"""Which platforms get a window icon handed over at runtime.

GTK needs a file, and Cocoa uses one as the dock image. Windows must not get one:
WinForms throws `Argument 'picture' must be a picture that can be used as a Icon`
on a .png and the window never opens. Handed nothing it takes the icon out of the
executable, which is the .ico already embedded there.

These tests keep that gate from widening back. It broke running from source on
Windows once, and a first fix then excluded macOS too, which needlessly cost it the
dock image.

Skipped where the desktop backend's own dependencies are not installed, which is
how the python CI job runs.
"""

import sys

import pytest

entry = pytest.importorskip(
    "docsigner_desktop.__main__", reason="needs the desktop backend's dependencies"
)


def test_windows_gets_no_icon(monkeypatch):
    """A .png here is fatal, and the .exe already carries the real one."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert entry._icon() is None


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_gtk_and_cocoa_get_the_png(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    icon = entry._icon()
    assert icon and icon.endswith("DocSigner.png"), (
        f"{platform} lost its icon: either the gate widened or "
        "desktop/packaging/DocSigner.png is gone (scripts/make_assets.py writes it)"
    )
