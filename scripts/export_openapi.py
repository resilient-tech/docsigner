#!/usr/bin/env python3
"""Write the server's OpenAPI document to server/openapi.json.

The document is committed so it can be reviewed like any other contract change
and consumed without running the server. `server/tests/test_openapi.py` fails
when it drifts, so a route change that would break generated clients shows up
as a diff in the pull request rather than in someone's build.

    python scripts/export_openapi.py

Generate a client from it in whatever language you use, for example:

    npx openapi-typescript server/openapi.json -o signer.d.ts
    openapi-generator generate -i server/openapi.json -g go -o ./signer
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO / "server" / "openapi.json"


def build() -> dict:
    """The spec, built without importing anything that needs configuration.

    signer_server.app reads the environment at import time; the defaults are
    enough to describe the routes, and nothing here starts a server.
    """
    sys.path.insert(0, str(REPO / "server"))
    from signer_server.app import app

    return app.openapi()


def render(spec: dict) -> str:
    # sort_keys so the file is a stable diff rather than a reshuffle whenever
    # FastAPI changes dictionary ordering.
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main() -> int:
    text = render(build())
    previous = SPEC_PATH.read_text() if SPEC_PATH.exists() else None
    SPEC_PATH.write_text(text)
    if previous == text:
        print(f"{SPEC_PATH.relative_to(REPO)} unchanged")
    else:
        print(f"{SPEC_PATH.relative_to(REPO)} written ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
