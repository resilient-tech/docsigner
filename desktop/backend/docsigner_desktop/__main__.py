"""Start the app.

    python -m docsigner_desktop            the real window
    python -m docsigner_desktop a.pdf b.pdf   open those, ready to sign
    python -m docsigner_desktop --server   no window, for UI work

Window mode serves the built UI, so run `pnpm build` first.
"""

import logging
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from . import openfiles, startup
from .app import app

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
DEV_PORT = 8000


def _serve(port: int) -> None:
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


def _free_port() -> int:
    # ponytail: tiny bind-release-rebind race, fine for one local app.
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _wait_until_serving(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("the backend did not start in time")


def _icon() -> str | None:
    """The window icon, handed over at runtime.

    Each toolkit takes only what it can read: WinForms an .ico, GTK and Cocoa the
    .png. A .png is not ignored by WinForms — it throws `Argument 'picture' must be
    a picture that can be used as a Icon` and the app never opens.

    None is a fine answer. A frozen Windows build carries no .ico beside it, since
    the spec embeds that in the .exe, and WinForms then lifts the icon out of the
    executable — the same image. From source, without this, it lifts python.exe's.
    """
    root = (
        Path(sys._MEIPASS)
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2] / "packaging"
    )
    icon = root / ("DocSigner.ico" if sys.platform == "win32" else "DocSigner.png")
    return str(icon) if icon.is_file() else None


def _claim_taskbar_identity() -> None:
    """Windows groups the taskbar button by process identity, not by window.

    With none set it falls back to the executable, so from source the button shows
    python.exe's icon while the title bar is already correct. Matches the macOS
    bundle identifier in the spec. Cosmetic, so a failure here is never worth
    stopping a launch for.
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p("tech.resilient.docsigner")
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("could not set the taskbar identity: %s", exc)


def main() -> None:
    # The signing host is its own binary now, shipped beside us. host.py finds it.
    startup.remember(sys.argv[1:])
    if "--server" in sys.argv:
        _serve(DEV_PORT)
        return
    try:
        import webview
    except ImportError:
        sys.exit(
            "pywebview is not installed. Run `pip install -r requirements.txt`, "
            "or use `--server` for headless UI development."
        )
    # Load Pillow before the window does. WebKitGTK brings the system freetype
    # and harfbuzz into the process, and Pillow's _imagingft carries its own
    # copies inside the wheel — auditwheel renames those files but not the
    # symbols in them. Whichever loads first owns FT_* for the whole process, so
    # a Pillow imported after the window binds to the system freetype and draws
    # every glyph blank: signed PDFs came out with an empty signature stamp.
    # _composed_stamp imports Pillow lazily, on the server thread, so without
    # this it always lost the race. Linux only in effect; Windows and macOS bind
    # per module, which is why the stamp was fine there.
    from PIL import Image, ImageDraw, ImageFont  # noqa: F401

    _claim_taskbar_identity()
    port = _free_port()
    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    _wait_until_serving(port)
    # Maximized, not fullscreen: the app is a three-column workspace and the
    # narrow default left the canvas cramped. pywebview maps this to each OS's own
    # "maximize", so the window keeps its title bar and controls.
    window = webview.create_window(
        "DocSigner Desktop", f"http://{HOST}:{port}", width=1200, height=820, maximized=True
    )

    # macOS hands over Open With files as an Apple event, not as arguments, and
    # only once the app has finished launching. Registering from `func` runs it
    # on the GUI thread after that, which is the only point AppKit's own handler
    # for the event is already in place to be replaced.
    #
    # A reload rather than a push: the UI reads /api/opened once on load and
    # prefers it over the last folder, so replaying that is all a second Open
    # With needs. No-op off macOS.
    def _listen() -> None:
        openfiles.install(on_files=lambda _paths: window.load_url(f"http://{HOST}:{port}"))

    webview.start(_listen, icon=_icon())


if __name__ == "__main__":
    main()
