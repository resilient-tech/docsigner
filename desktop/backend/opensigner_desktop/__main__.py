"""Run the OpenSigner desktop app.

    python -m opensigner_desktop            native window over the local server
    python -m opensigner_desktop --server   headless server on :8000 (UI dev)

Window mode serves the built frontend from frontend/dist (run `pnpm build`
first). For UI work, run --server here and `pnpm dev` in ../frontend against it.
"""

import socket
import sys
import threading
import time

import uvicorn

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
    # In a frozen build the app re-execs itself as the signing host (host.py),
    # since a PyInstaller bundle can't run `python -m signer_host.cli`.
    if len(sys.argv) > 1 and sys.argv[1] == "--host-cli":
        from signer_host.cli import main as host_cli

        raise SystemExit(host_cli(sys.argv[2:]))
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
    webview.create_window("OpenSigner Desktop", f"http://{HOST}:{port}", width=1200, height=820)
    webview.start()


if __name__ == "__main__":
    main()
