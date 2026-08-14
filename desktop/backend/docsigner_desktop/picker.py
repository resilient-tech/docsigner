"""Real file and folder dialogs, so nobody has to paste a path.

pywebview draws these with the platform's own picker — the Vista dialog on
Windows, NSOpenPanel on macOS, GTK's chooser on Linux — so there is nothing
per-OS to do here. It used to be macOS-only `osascript`, which left both buttons
silently dead on Windows and Linux.

--server has no window, so the pickers return nothing there and the UI falls back
to its paste-a-path box.
"""

from pathlib import Path

from . import store

try:
    import webview
except ImportError:  # no GUI toolkit installed; --server still works
    webview = None


def _start_dir() -> str:
    """Open where the user already is, rather than their home folder.

    The frontend keeps `last_folder` in settings as soon as a folder loads, so
    this needs no argument from the caller. Empty string means "your choice",
    which is what pywebview falls back to.
    """
    last = store.load_settings().last_folder
    return last if last and Path(last).is_dir() else ""


def _dialog(kind: str, **kwargs) -> tuple:
    """Show one of pywebview's native dialogs. Empty tuple if cancelled.

    Called from a FastAPI handler, so off the GUI thread: each backend deals with
    that itself (GTK hops through its main loop, Cocoa through the main thread).
    FastAPI runs sync endpoints in a threadpool, so the modal dialog blocks one
    worker rather than the whole server.
    """
    if webview is None or not webview.windows:
        return ()
    kwargs.setdefault("directory", _start_dir())
    dialog_type = getattr(webview.FileDialog, kind)
    return webview.windows[0].create_file_dialog(dialog_type, **kwargs) or ()


def pick_folder() -> str | None:
    chosen = _dialog("FOLDER")
    return str(chosen[0]) if chosen else None


def pick_files() -> list[dict]:
    # The dialog filter is a hint, not a guarantee: every picker lets you widen it
    # to all files, so check the suffix here too.
    entries = []
    for name in _dialog("OPEN", allow_multiple=True, file_types=("PDF files (*.pdf)",)):
        p = Path(name)
        if p.suffix.lower() == ".pdf" and p.is_file():
            entries.append({"path": str(p), "name": p.name, "size": p.stat().st_size})
    return entries
