"""Run the server. Port 8001 unless PORT says otherwise."""

import os

import uvicorn

from .app import app


def main() -> None:
    # Long keep-alive because the user is standing at a PIN prompt. The 5s
    # default drops the connection under them and the next POST dies on it.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8001")),
        timeout_keep_alive=300,
    )


if __name__ == "__main__":
    main()
