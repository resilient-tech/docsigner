"""Raise the repo's version by one patch, in every file that states it.

    python scripts/bump_version.py              # 0.2.0 -> 0.2.1, prints 0.2.1
    python scripts/bump_version.py 0.3.0        # set it outright
    python scripts/bump_version.py --selftest   # no files touched

There is one version for the whole repo and `host/Cargo.toml` is where it lives.
Three other places restate it and every one of them is load-bearing:
`Cargo.lock` (or the next cargo build rewrites it and dirties the tree), the
extension manifest (the stores key their updates off it), and nothing else --
the PyInstaller spec and the Homebrew files read `Cargo.toml` at build time on
purpose.

Called by the release workflow on a push to master, before it tags. Safe to run
by hand: it only rewrites the version line, and prints what it moved to.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (path, pattern). Each pattern must have one group holding the version and must
# match the version line and nothing else. Only the first match is replaced:
# Cargo.lock states a version for every dependency and ours is not the first.
TARGETS = [
    ("host/Cargo.toml", r'(?m)^version = "([^"]+)"'),
    ("host/Cargo.lock", r'(?ms)^name = "docsigner-host"\nversion = "([^"]+)"'),
    ("extension/manifest.json", r'"version": "([^"]+)"'),
]


def next_patch(version):
    """0.2.0 -> 0.2.1. Anything that is not three numbers is a mistake, loudly."""
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"error: {version!r} is not a major.minor.patch version")
    major, minor, patch = (int(p) for p in parts)
    return f"{major}.{minor}.{patch + 1}"


def current(root=REPO):
    path, pattern = TARGETS[0]
    match = re.search(pattern, (root / path).read_text())
    if not match:
        raise SystemExit(f"error: no version line in {path}")
    return match.group(1)


def bump(version=None, root=REPO):
    """Write `version` (default: one patch up) everywhere. Returns what it wrote."""
    version = version or next_patch(current(root))
    for path, pattern in TARGETS:
        file = root / path
        text = file.read_text()
        match = re.search(pattern, text)
        if not match:
            raise SystemExit(f"error: no version line in {path}")
        start, end = match.span(1)
        file.write_text(text[:start] + version + text[end:])
    return version


def selftest():
    """The whole point is that it edits one number and leaves the file alone."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "host").mkdir()
        (root / "extension").mkdir()
        (root / "host/Cargo.toml").write_text(
            '[package]\nname = "docsigner-host"\nversion = "0.2.0"\nedition = "2021"\n'
        )
        # A dependency's version line comes first on purpose: replacing the
        # wrong one is the failure this guards against.
        (root / "host/Cargo.lock").write_text(
            '[[package]]\nname = "aho-corasick"\nversion = "1.1.3"\n\n'
            '[[package]]\nname = "docsigner-host"\nversion = "0.2.0"\n'
        )
        (root / "extension/manifest.json").write_text(
            '{\n  "manifest_version": 3,\n  "version": "0.2.0"\n}\n'
        )

        assert current(root) == "0.2.0"
        assert bump(root=root) == "0.2.1"
        assert 'version = "0.2.1"\nedition' in (root / "host/Cargo.toml").read_text()

        lock = (root / "host/Cargo.lock").read_text()
        assert 'name = "aho-corasick"\nversion = "1.1.3"' in lock, "hit the wrong package"
        assert 'name = "docsigner-host"\nversion = "0.2.1"' in lock

        manifest = (root / "extension/manifest.json").read_text()
        assert '"manifest_version": 3' in manifest, "manifest_version is not a version"
        assert '"version": "0.2.1"' in manifest

        assert bump("1.0.0", root=root) == "1.0.0"
        assert current(root) == "1.0.0"

    assert next_patch("0.9.9") == "0.9.10"
    for bad in ("0.2", "v0.2.0", "0.2.0-rc1"):
        try:
            next_patch(bad)
        except SystemExit:
            continue
        raise AssertionError(f"{bad!r} should have been refused")

    print("selftest ok")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg == "--selftest":
        selftest()
    else:
        print(bump(arg))
