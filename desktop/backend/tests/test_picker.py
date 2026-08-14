"""The folder and file pickers.

These used to be macOS-only, which left both buttons silently dead on Windows and
Linux. The dialogs themselves are pywebview's, so what is worth testing is the
two things around them: that no window degrades quietly, and that a chosen file
is still checked before it reaches the file list.

pywebview is deliberately not installed for this suite (see the python job in
.github/workflows/test.yml), so everything here runs against a stub. The one test
that touches the real module skips itself when it is absent.
"""

import pytest

from docsigner_desktop import picker
from docsigner_desktop.models import Settings


class _FakeFileDialog:
    """Mirrors pywebview's FileDialog. Guarded by the last test in this file."""

    OPEN = 10
    FOLDER = 20
    SAVE = 30


class _FakeWindow:
    """Records what it was asked for and hands back a canned answer."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def create_file_dialog(self, dialog_type, **kwargs):
        self.calls.append((dialog_type, kwargs))
        return self.answer


class _FakeWebview:
    FileDialog = _FakeFileDialog

    def __init__(self, windows):
        self.windows = windows


@pytest.fixture(autouse=True)
def _no_window_no_settings(monkeypatch):
    """Default: headless, and never read the real user's settings file."""
    monkeypatch.setattr(picker, "webview", _FakeWebview([]))
    monkeypatch.setattr(picker.store, "load_settings", lambda: Settings())


def _with_window(monkeypatch, answer):
    win = _FakeWindow(answer)
    monkeypatch.setattr(picker, "webview", _FakeWebview([win]))
    return win


def test_no_window_means_no_picker():
    """--server runs headless; the UI falls back to its paste-a-path box."""
    assert picker.pick_folder() is None
    assert picker.pick_files() == []


def test_pywebview_missing_does_not_crash(monkeypatch):
    """The python test job installs no GUI toolkit at all."""
    monkeypatch.setattr(picker, "webview", None)
    assert picker.pick_folder() is None
    assert picker.pick_files() == []


def test_cancelling_returns_nothing(monkeypatch):
    """Every backend returns None when the user cancels."""
    _with_window(monkeypatch, None)
    assert picker.pick_folder() is None
    _with_window(monkeypatch, None)
    assert picker.pick_files() == []


def test_pick_folder_asks_for_a_folder(monkeypatch, tmp_path):
    win = _with_window(monkeypatch, (str(tmp_path),))
    assert picker.pick_folder() == str(tmp_path)
    assert win.calls[0][0] == _FakeFileDialog.FOLDER


def test_pick_files_allows_multiple_and_filters_to_pdf(monkeypatch, tmp_path):
    good = tmp_path / "invoice.pdf"
    good.write_bytes(b"%PDF-1.7\n")
    shouty = tmp_path / "SHOUTY.PDF"  # suffix case must not matter
    shouty.write_bytes(b"%PDF-1.7\n")
    not_a_pdf = tmp_path / "notes.txt"
    not_a_pdf.write_text("hello")
    missing = tmp_path / "deleted.pdf"  # picked, then gone before we looked

    win = _with_window(monkeypatch, tuple(str(p) for p in (good, shouty, not_a_pdf, missing)))
    entries = picker.pick_files()

    assert [e["name"] for e in entries] == ["invoice.pdf", "SHOUTY.PDF"]
    assert entries[0]["size"] == good.stat().st_size
    assert entries[0]["path"] == str(good)

    dialog_type, kwargs = win.calls[0]
    assert dialog_type == _FakeFileDialog.OPEN
    assert kwargs["allow_multiple"] is True
    # A filter the user can widen, so the suffix check above still has to exist.
    assert kwargs["file_types"] == ("PDF files (*.pdf)",)


def test_dialog_opens_in_the_folder_already_loaded(monkeypatch, tmp_path):
    """Not the home folder: the user is almost always working in one place."""
    monkeypatch.setattr(picker.store, "load_settings",
                        lambda: Settings(last_folder=str(tmp_path)))
    win = _with_window(monkeypatch, (str(tmp_path),))
    picker.pick_folder()
    assert win.calls[0][1]["directory"] == str(tmp_path)


def test_a_stale_or_absent_last_folder_is_ignored(monkeypatch, tmp_path):
    """A folder that has since been deleted must not break the picker."""
    for bad in (None, str(tmp_path / "gone"), __file__):  # missing, and a file
        monkeypatch.setattr(picker.store, "load_settings",
                            lambda bad=bad: Settings(last_folder=bad))
        win = _with_window(monkeypatch, None)
        assert picker.pick_folder() is None
        assert win.calls[0][1]["directory"] == ""


def test_the_stub_still_matches_pywebview():
    """Everything above trusts _FakeFileDialog's numbers. Catch a drift."""
    webview = pytest.importorskip("webview", reason="not installed in the python CI job")
    assert _FakeFileDialog.OPEN == webview.FileDialog.OPEN
    assert _FakeFileDialog.FOLDER == webview.FileDialog.FOLDER
