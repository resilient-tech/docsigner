"""Start the app.

    python -m docsigner_desktop            the real window
    python -m docsigner_desktop a.pdf b.pdf   open those, ready to sign
    python -m docsigner_desktop --server   no window, for UI work

Window mode serves the built UI, so run `pnpm build` first.
"""

import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from . import startup
from .app import app

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
    """The window icon, for the one OS that needs it handed over at runtime.

    Windows embeds the .ico in the .exe and macOS takes the .icns from the app
    bundle. GTK has neither, and with no icon the Linux taskbar shows a generic
    placeholder.

    Linux only, and not merely as a tidy-up: WinForms does not ignore an icon it
    cannot use, it throws `Argument 'picture' must be a picture that can be used
    as a Icon` and the app never opens. A packaged Windows build escaped that
    because the spec only bundles the .png on Linux, so running from source was
    the only place it bit. The spec's check and this one have to agree.
    """
    if not sys.platform.startswith("linux"):
        return None
    root = (
        Path(sys._MEIPASS)
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2] / "packaging"
    )
    icon = root / "DocSigner.png"
    return str(icon) if icon.is_file() else None


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

    port = _free_port()
    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    _wait_until_serving(port)
    # Maximized, not fullscreen: the app is a three-column workspace and the
    # narrow default left the canvas cramped. pywebview maps this to each OS's own
    # "maximize", so the window keeps its title bar and controls.
    webview.create_window(
        "DocSigner Desktop", f"http://{HOST}:{port}", width=1200, height=820, maximized=True
    )
    webview.start(icon=_icon())


if __name__ == "__main__":
    main()
