"""PDFs the app was launched with: "Open With", a drag onto the icon, or paths
typed on the command line.

Filled once by __main__ before the window opens, read once by the UI.
"""

from pathlib import Path

PATHS: list[str] = []


def remember(argv: list[str]) -> None:
    """Everything that is not a flag is a path."""
    PATHS[:] = [a for a in argv if not a.startswith("-")]


def listing() -> dict:
    """The {folder, files} shape the folder and picker endpoints return, plus
    whatever was handed over that this app cannot open.

    One folder behaves like choosing it. Anything else is taken as a list of
    files, so several PDFs opened together arrive as one batch. `ignored` is what
    the UI needs to say why nothing appeared: a user can point "Open with" at any
    file type, and being handed a .txt should not look like the app failed.
    """
    paths = [Path(p).expanduser() for p in PATHS]
    ignored: list[str] = []
    if len(paths) == 1 and paths[0].is_dir():
        base = paths[0]
        files = sorted(f for f in base.glob("*.pdf") if f.is_file())
    else:
        files = [p for p in paths if p.is_file() and p.suffix.lower() == ".pdf"]
        ignored = [p.name for p in paths if p not in files]
        base = files[0].parent if files else None
    return {
        "folder": str(base) if base else None,
        "files": [{"path": str(f), "name": f.name, "size": f.stat().st_size} for f in files],
        "ignored": ignored,
    }
