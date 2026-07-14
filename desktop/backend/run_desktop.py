"""Frozen-build entry point.

PyInstaller runs its entry script as the top-level `__main__`, with no package
around it, so a package's own `__main__.py` (with relative imports like
`from .app import app`) can't be the entry. Start through the package instead,
which gives those imports their package context. `python -m opensigner_desktop`
still uses the package's `__main__.py` directly.
"""

from opensigner_desktop.__main__ import main

if __name__ == "__main__":
    main()
