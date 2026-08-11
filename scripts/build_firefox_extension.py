"""Make the Firefox copy of the extension.

One manifest cannot please both. Chrome refuses the background style Firefox
needs, and Firefox ignores Chrome's. So extension/ stays Chrome-shaped and this
writes a Firefox version beside it.

    python scripts/build_firefox_extension.py
"""

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "extension"
DEST = ROOT / "dist" / "firefox-extension"


def main() -> None:
    shutil.rmtree(DEST, ignore_errors=True)
    shutil.copytree(SRC, DEST)
    manifest_path = DEST / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["background"] = {"scripts": ["background.js"]}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Firefox extension written to {DEST}")


if __name__ == "__main__":
    main()
