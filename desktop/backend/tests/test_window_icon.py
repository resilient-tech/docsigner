"""Which platforms get a window icon handed over at runtime.

Linux needs a file, because GTK has nowhere to embed one. Windows and macOS carry
their own icon in the binary, and Windows does **not** politely ignore one it
cannot use: WinForms throws `Argument 'picture' must be a picture that can be used
as a Icon` on a .png and the window never opens.

The spec gates the bundled .png on Linux too. These tests are what keeps the two
gates agreeing — they disagreed once, and running from source on Windows broke.

Skipped where the desktop backend's own dependencies are not installed, which is
how the python CI job runs.
"""

import sys

import pytest

entry = pytest.importorskip(
    "docsigner_desktop.__main__", reason="needs the desktop backend's dependencies"
)


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_no_runtime_icon_off_linux(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    assert entry._icon() is None


def test_linux_gets_the_png(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    icon = entry._icon()
    assert icon and icon.endswith("DocSigner.png"), (
        "Linux lost its taskbar icon: either the gate changed or "
        "desktop/packaging/DocSigner.png is gone (scripts/make_assets.py writes it)"
    )
