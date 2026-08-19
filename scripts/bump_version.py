"""Read and raise version numbers, one component at a time.

    python scripts/bump_version.py                  # print every version
    python scripts/bump_version.py core             # 0.1.0 -> 0.1.1
    python scripts/bump_version.py core minor       # 0.1.0 -> 0.2.0
    python scripts/bump_version.py host 1.0.0       # set it outright
    python scripts/bump_version.py --auto v0.1.0    # patch-bump whatever changed
    python scripts/bump_version.py --check v0.1.0   # what changed but was not bumped
    python scripts/bump_version.py --selftest       # no files touched

Each component owns its own number, because each one is published somewhere
different: `core` to PyPI, `js` to npm, `extension` to the stores, `host` as a
binary. A component's number moves only when its folder changes, so nobody gets
an update with nothing in it.

`release` is the odd one out: it numbers the GitHub Release that carries all of
them, so it moves every time. The desktop app has no number of its own -- it is
a bundle of core and host, so it ships as the release.

The release workflow calls `--auto` for you, so an ordinary release needs none of
this: merge to master and every changed component gets a patch bump. Run a
command here only to make a bump bigger than a patch, on `develop` before the
merge -- `--auto` then leaves that component alone, since its version has
already moved.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# component -> (folder it covers, [(file, pattern), ...]). Each pattern must have
# one group holding the version and must match the version line and nothing else.
# Only the first match is replaced: Cargo.lock states a version for every
# dependency and ours is not the first.
#
# `release` covers no folder: it is the release number, not a component's, so
# "did this folder change" does not apply to it.
COMPONENTS = {
    "release": (None, [("VERSION", r"(?m)^(\d+\.\d+\.\d+)\s*$")]),
    "host": (
        "host",
        [
            ("host/Cargo.toml", r'(?m)^version = "([^"]+)"'),
            ("host/Cargo.lock", r'(?ms)^name = "docsigner-host"\nversion = "([^"]+)"'),
        ],
    ),
    "core": ("core", [("core/pyproject.toml", r'(?m)^version = "([^"]+)"')]),
    "js": ("js", [("js/package.json", r'"version": "([^"]+)"')]),
    "extension": ("extension", [("extension/manifest.json", r'"version": "([^"]+)"')]),
}


def next_version(version, kind="patch"):
    """0.2.0 -> 0.2.1, 0.3.0 or 1.0.0. Anything else is a mistake, loudly."""
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"error: {version!r} is not a major.minor.patch version")
    major, minor, patch = (int(p) for p in parts)
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "major":
        return f"{major + 1}.0.0"
    raise SystemExit(f"error: {kind!r} is not patch, minor, major or a version")


def current(component, root=REPO):
    """The version in that component's first file."""
    path, pattern = COMPONENTS[component][1][0]
    match = re.search(pattern, (root / path).read_text())
    if not match:
        raise SystemExit(f"error: no version line in {path}")
    return match.group(1)


def bump(component, kind="patch", root=REPO):
    """Write the new version in every file that states it. Returns what it wrote."""
    version = kind if re.fullmatch(r"\d+\.\d+\.\d+", kind) else next_version(current(component, root), kind)
    for path, pattern in COMPONENTS[component][1]:
        file = root / path
        text = file.read_text()
        match = re.search(pattern, text)
        if not match:
            raise SystemExit(f"error: no version line in {path}")
        start, end = match.span(1)
        file.write_text(text[:start] + version + text[end:])
    return version


def _git(*args, root=REPO):
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True
    )


def check(previous, root=REPO):
    """Name every component whose folder changed since `previous` without a bump.

    The one mistake this release flow can make: edit core, forget the number,
    and publish a PyPI release that claims to be the old one. Returns the list
    of offenders so the caller decides whether to fail.
    """
    stale = []
    for name, (folder, _files) in COMPONENTS.items():
        if folder is None:
            continue
        changed = _git("diff", "--quiet", previous, "--", f"{folder}/", root=root).returncode != 0
        if not changed:
            continue
        was = _git("show", f"{previous}:{COMPONENTS[name][1][0][0]}", root=root)
        if was.returncode != 0:
            continue  # the file did not exist then; nothing to compare against
        old = re.search(COMPONENTS[name][1][0][1], was.stdout)
        if old and old.group(1) == current(name, root):
            stale.append(name)
    return stale


def auto(previous, root=REPO):
    """Patch-bump every component whose folder changed, and the release with it.

    Patch, always: it is what almost every release is, and guessing between
    patch and minor is not worth a manual step on every release. `minor` and
    `major` stay a typed decision for the releases that need one -- run one by
    hand on develop before merging and this leaves that component alone,
    because by then its version has already moved.

    The release number moves whether or not a component did. Something is being
    released, so it needs a tag nobody has used.
    """
    moved = {}
    for name in check(previous, root) + ["release"]:
        was = current(name, root)
        moved[name] = (was, bump(name, "patch", root=root))
    return moved


def _scaffold(root):
    """A miniature repo: one version file per component, all at 0.1.0."""
    for folder in ("host", "extension", "core", "js"):
        (root / folder).mkdir()
    (root / "VERSION").write_text("0.1.0\n")
    (root / "host/Cargo.toml").write_text(
        '[package]\nname = "docsigner-host"\nversion = "0.1.0"\nedition = "2021"\n'
    )
    # A dependency's version line comes first on purpose: replacing the wrong
    # one is the failure this guards against.
    (root / "host/Cargo.lock").write_text(
        '[[package]]\nname = "aho-corasick"\nversion = "1.1.3"\n\n'
        '[[package]]\nname = "docsigner-host"\nversion = "0.1.0"\n'
    )
    (root / "extension/manifest.json").write_text(
        '{\n  "manifest_version": 3,\n  "version": "0.1.0"\n}\n'
    )
    (root / "core/pyproject.toml").write_text(
        '[project]\nname = "docsigner-core"\nversion = "0.1.0"\n'
    )
    (root / "js/package.json").write_text(
        '{\n  "name": "docsigner",\n  "version": "0.1.0"\n}\n'
    )


def _selftest_auto():
    """--auto decides every release now, so it is checked against a real repo.

    Three things have to hold, and only the first is obvious: a changed folder
    is bumped, an unchanged one is not, and one already bumped by hand is left
    at the number the human chose.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _scaffold(root)

        def git(*args):
            done = _git(*args, root=root)
            assert done.returncode == 0, f"git {args[0]} failed: {done.stderr}"
            return done

        git("init", "-q")
        git("config", "user.email", "selftest@example.invalid")
        git("config", "user.name", "selftest")
        git("add", "-A")
        git("commit", "-qm", "first")
        git("tag", "v0.1.0")

        assert check("v0.1.0", root) == [], "nothing changed yet"

        (root / "extension/background.js").write_text("// a change\n")
        git("add", "-A")
        git("commit", "-qm", "change the extension")
        assert check("v0.1.0", root) == ["extension"]

        moved = auto("v0.1.0", root)
        assert moved == {
            "extension": ("0.1.0", "0.1.1"),
            "release": ("0.1.0", "0.1.1"),
        }, moved
        assert current("core", root) == "0.1.0", "core did not change; leave it alone"

        # A minor bump typed by hand on develop must survive the automatic pass.
        git("add", "-A")
        git("commit", "-qm", "release")
        git("tag", "v0.1.1")
        (root / "core/engine.py").write_text("# a feature\n")
        bump("core", "minor", root=root)
        git("add", "-A")
        git("commit", "-qm", "feat: something")
        assert check("v0.1.1", root) == [], "already bumped, so not stale"
        assert auto("v0.1.1", root) == {"release": ("0.1.1", "0.1.2")}
        assert current("core", root) == "0.2.0", "the typed minor must survive"


def selftest():
    """The whole point is that it edits one number and leaves the file alone."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _scaffold(root)

        for name in COMPONENTS:
            assert current(name, root) == "0.1.0", name

        # One component moves and the others do not: that is the whole change.
        assert bump("core", root=root) == "0.1.1"
        assert current("core", root) == "0.1.1"
        assert current("host", root) == "0.1.0"

        assert bump("host", "minor", root=root) == "0.2.0"
        assert bump("js", "major", root=root) == "1.0.0"
        assert bump("release", "2.5.3", root=root) == "2.5.3"
        assert (root / "VERSION").read_text() == "2.5.3\n", "the newline must survive"

        lock = (root / "host/Cargo.lock").read_text()
        assert 'name = "aho-corasick"\nversion = "1.1.3"' in lock, "hit the wrong package"
        assert 'name = "docsigner-host"\nversion = "0.2.0"' in lock

        assert bump("extension", root=root) == "0.1.1"
        manifest = (root / "extension/manifest.json").read_text()
        assert '"manifest_version": 3' in manifest, "manifest_version is not a version"
        assert '"version": "0.1.1"' in manifest

    assert next_version("0.9.9") == "0.9.10"
    assert next_version("0.9.9", "minor") == "0.10.0"
    assert next_version("1.2.3", "major") == "2.0.0"
    for bad in ("0.2", "v0.2.0", "0.2.0-rc1"):
        try:
            next_version(bad)
        except SystemExit:
            continue
        raise AssertionError(f"{bad!r} should have been refused")

    _selftest_auto()
    print("selftest ok")


def main(argv):
    if argv and argv[0] == "--selftest":
        return selftest()

    if argv and argv[0] == "--auto":
        if len(argv) < 2:
            raise SystemExit("error: --auto needs the previous tag, e.g. --auto v0.1.0")
        for name, (was, now) in auto(argv[1]).items():
            print(f"{name} {was} -> {now}")
        return None

    if argv and argv[0] == "--check":
        if len(argv) < 2:
            raise SystemExit("error: --check needs the previous tag, e.g. --check v0.1.0")
        stale = check(argv[1])
        if stale:
            raise SystemExit(
                "error: changed since %s but not bumped: %s\n"
                "Run: %s"
                % (
                    argv[1],
                    ", ".join(stale),
                    "  ".join(f"python scripts/bump_version.py {n}" for n in stale),
                )
            )
        print(f"every changed component was bumped since {argv[1]}")
        return None

    if not argv:
        width = max(len(n) for n in COMPONENTS)
        for name in COMPONENTS:
            print(f"{name:<{width}}  {current(name)}")
        return None

    component = argv[0]
    if component not in COMPONENTS:
        raise SystemExit(
            f"error: {component!r} is not a component. Pick one of: "
            + ", ".join(COMPONENTS)
        )
    print(bump(component, argv[1] if len(argv) > 1 else "patch"))
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
