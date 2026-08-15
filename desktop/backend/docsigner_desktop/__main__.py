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
    port = _free_port()
    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    _wait_until_serving(port)
    # Maximized, not fullscreen: the app is a three-column workspace and the
    # narrow default left the canvas cramped. pywebview maps this to each OS's own
    # "maximize", so the window keeps its title bar and controls.
    webview.create_window(
        "DocSigner Desktop", f"http://{HOST}:{port}", width=1200, height=820, maximized=True
    )
    webview.start()


if __name__ == "__main__":
    main()
