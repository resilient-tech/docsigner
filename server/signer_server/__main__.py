"""`python -m signer_server` runs the reference server on port 8000."""

import uvicorn

from .app import app


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
