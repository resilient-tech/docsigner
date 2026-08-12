#!/usr/bin/env python3
"""Copy the tokens into the one consumer that cannot reach up to design/.

    python3 design/sync.py            # write the copies
    python3 design/sync.py --check    # exit non-zero if a copy is stale

site/ and desktop/frontend/ both `@import` design/tokens.css directly: their
bundlers resolve a relative path at build time, so there is nothing to copy.

The extension cannot. Its zip is `cd extension && zip -r . `, so whatever is not
inside extension/ does not ship, and a browser extension has no build step to
add one. So the token file is copied in, and this script is what stops that copy
from becoming the fourth hand-maintained divergent version -- which is the exact
problem design/ was created to end.

CI runs --check, so a change to design/tokens.css that forgets to sync fails the
build rather than shipping a consent dialog on last month's colours.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

HEADER = """/*
 * GENERATED -- do not edit. Source: design/tokens.css
 *
 * Regenerate with:  python3 design/sync.py
 *
 * This copy exists because the extension ships as a zip of extension/ with no
 * build step, so it cannot @import the shared file the way site/ and
 * desktop/frontend/ do. CI asserts it is current.
 */
"""

# (source, destination) pairs.
COPIES = [(HERE / "tokens.css", ROOT / "extension" / "tokens.css")]


def rendered(src: Path) -> str:
    return HEADER + "\n" + src.read_text(encoding="utf-8")


def main() -> int:
    check = "--check" in sys.argv
    stale: list[str] = []

    for src, dest in COPIES:
        want = rendered(src)
        have = dest.read_text(encoding="utf-8") if dest.exists() else None
        rel = dest.relative_to(ROOT)
        if have == want:
            print(f"ok      {rel}")
            continue
        if check:
            stale.append(str(rel))
            print(f"STALE   {rel}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(want, encoding="utf-8")
            print(f"written {rel}")

    if stale:
        print(
            f"\n{len(stale)} copy(ies) out of date. Run: python3 design/sync.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
