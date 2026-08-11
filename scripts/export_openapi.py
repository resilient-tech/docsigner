#!/usr/bin/env python3
"""Write the API description to server/openapi.json.

It is committed, so a change to the API shows up as a diff in the pull request
instead of breaking someone's generated client later. A test fails if it drifts.

    python scripts/export_openapi.py
    npx openapi-typescript server/openapi.json -o signer.d.ts
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO / "server" / "openapi.json"


def build() -> dict:
    """Build the description. Starts no server, needs no configuration."""
    sys.path.insert(0, str(REPO / "server"))
    from signer_server.app import app

    return app.openapi()


def render(spec: dict) -> str:
    # Sorted, so the diff shows real changes and not a reshuffle.
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
