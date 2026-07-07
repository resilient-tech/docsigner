"""`python -m signer_server` runs the reference server. Port defaults to 8001;
override with the PORT env var (or a PORT line in .env)."""

import os

import uvicorn

from .app import app


def main() -> None:
    # timeout_keep_alive: uvicorn's 5s default closes the browser's pooled
    # connection while the user is at the token PIN prompt; Chrome then fails
    # the complete POST on the dead socket instead of retrying. 300s covers
    # any realistic PIN entry.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8001")),
        timeout_keep_alive=300,
    )


if __name__ == "__main__":
    main()
