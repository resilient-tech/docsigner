"""Tables in docs that rot on their own: module maps, and the site's repo links.

The module map is the one part of a doc that rots on its own: add a file, and the
list is wrong with nobody noticing. Everything else in a doc changes when the
design changes, which is the moment you'd rewrite it anyway.

Forward direction only (a file with no doc line fails). A rename fails the same
way, since the new name is the one that's missing.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

MAPS = [
    ("core/docsigner_core", "*.py", "docs/core.md"),
    ("server/docsigner_server", "*.py", "docs/server.md"),
    ("desktop/backend/docsigner_desktop", "*.py", "docs/desktop.md"),
    ("host/src", "*.rs", "docs/host.md"),
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


# The site links to files in this repo by path. A rename or a move breaks the
# link silently, and a visitor gets GitHub's 404 instead of the doc. Same rot as
# a module map, so it's checked the same way.
SITE_CONFIG = REPO / "site/src/config.ts"
BLOB = re.compile(r"\$\{REPO\}/blob/HEAD/([^`]+)`")


@pytest.mark.parametrize(
    "path", sorted(set(BLOB.findall(SITE_CONFIG.read_text(encoding="utf-8"))))
)
def test_site_links_to_files_that_exist(path):
    assert (REPO / path).is_file(), (
        f"site/src/config.ts links to {path}, which is not in the repo. "
        "Fix the link or restore the file."
    )
