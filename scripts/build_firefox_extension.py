"""Emit the Firefox copy of the extension.

One manifest cannot serve both browser families: Chrome refuses to load an
MV3 manifest that carries background.scripts ("requires manifest version of
2 or lower"), and Firefox does not run background.service_worker. So
extension/ stays Chrome-shaped, and this script writes
dist/firefox-extension/ with the background switched to an event page.

Usage: python scripts/build_firefox_extension.py
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
