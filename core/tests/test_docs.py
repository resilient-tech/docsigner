"""Every source file is named in its module map.

The module map is the one part of a doc that rots on its own: add a file, and the
list is wrong with nobody noticing. Everything else in a doc changes when the
design changes, which is the moment you'd rewrite it anyway.

Forward direction only (a file with no doc line fails). A rename fails the same
way, since the new name is the one that's missing.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

MAPS = [
    ("core/signer_core", "*.py", "docs/core.md"),
    ("server/signer_server", "*.py", "docs/server.md"),
    ("desktop/backend/docsigner_desktop", "*.py", "docs/desktop.md"),
    ("host-rs/src", "*.rs", "docs/host.md"),
]

SKIP = {"__init__.py"}


def _cases():
    for src, pattern, doc in MAPS:
        for path in sorted((REPO / src).glob(pattern)):
            if path.name not in SKIP:
                yield pytest.param(path, REPO / doc, id=f"{doc}:{path.name}")


@pytest.mark.parametrize("source,doc", list(_cases()))
def test_module_map_names_every_file(source, doc):
    assert source.name in doc.read_text(encoding="utf-8"), (
        f"{source.name} is missing from {doc.relative_to(REPO)}. "
        "Add a line to its module map."
    )
