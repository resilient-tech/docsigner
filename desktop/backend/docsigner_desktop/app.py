"""The routes the window talks to. In a real build it also serves the UI."""

import logging
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import docsigner_core

from . import certs, config, fonts, picker, signing, startup, store
from .models import FontUpload, Settings, SignRequest

app = FastAPI(title="DocSigner Desktop")
config.setup_logging()
log = logging.getLogger(__name__)
fonts.load()  # the user's uploaded faces, before the first stamp is drawn


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/config")
def get_config() -> dict:
    return config.info()


@app.get("/api/identities")
def identities() -> dict:
    """Who can sign, plus a hint when a token is there but unusable.

    One scan feeds both, so the list and the reason it is empty always agree.
    """
    return {
        "identities": certs.list_identities(store.KEYS_DIR),
        "tokenHint": certs.token_hint(),
    }


@app.get("/api/opened")
def opened() -> dict:
    """PDFs the app was launched with. Empty when it was started on its own."""
    return startup.listing()


@app.post("/api/pick-folder")
def pick_folder() -> dict:
    """Open a native folder chooser; returns the chosen path (null if cancelled)."""
    return {"folder": picker.pick_folder()}


@app.post("/api/pick-files")
def pick_files() -> dict:
    """Open a native multi-file chooser; returns the chosen PDFs."""
    files = picker.pick_files()
    folder = str(Path(files[0]["path"]).parent) if files else None
    return {"folder": folder, "files": files}


@app.get("/api/folder")
def folder(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        raise HTTPException(404, "That folder or file does not exist.")
    if p.is_file():
        files = [p] if p.suffix.lower() == ".pdf" else []
        base = p.parent
    else:
        files = sorted(x for x in p.glob("*.pdf") if x.is_file())
        base = p
    return {
        "folder": str(base),
        "files": [{"path": str(f), "name": f.name, "size": f.stat().st_size} for f in files],
    }


@app.get("/api/page")
def page(path: str, index: int = -1, width: int = 1000) -> dict:
    try:
        return docsigner_core.render_page(str(Path(path).expanduser()), index, width)
    except docsigner_core.SignerError as exc:
        # The window gets the plain sentence; the log keeps what pdfium said.
        log.warning("could not open %s: %r", path, exc.__cause__ or exc)
        raise HTTPException(400, exc.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not render this page: {exc}")


@app.get("/api/settings")
def get_settings() -> Settings:
    return store.load_settings()


@app.put("/api/settings")
def put_settings(s: Settings) -> dict:
    store.save_settings(s)
    return {"ok": True}


@app.post("/api/sign")
def sign(req: SignRequest) -> dict:
    if not req.files:
        raise HTTPException(400, "No files to sign.")
    return {"results": signing.sign_files(req)}


# ---- stamp fonts -----------------------------------------------------------
# The preview loads the same font files that go into the PDF, so what is on
# screen is what gets signed. A slug is looked up in a list, never used as a path.

@app.get("/api/fonts")
def list_fonts() -> list[dict]:
    return fonts.listing()


@app.post("/api/fonts")
def add_font(upload: FontUpload) -> dict:
    try:
        slug = fonts.save(upload.filename, upload.data)
    except fonts.FontError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"slug": slug, "fonts": fonts.listing()}


@app.delete("/api/fonts/{slug}")
def remove_font(slug: str) -> dict:
    try:
        fonts.delete(slug)
    except fonts.FontError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"fonts": fonts.listing()}


@app.get("/font-file/{slug}")
def font_file(slug: str) -> FileResponse:
    path = fonts.path_for(slug)
    if path is None or not Path(path).is_file():
        raise HTTPException(404, "No such font.")
    return FileResponse(str(path), media_type="font/ttf")


def _bundle_root() -> Path:
    # Packaged builds unpack elsewhere, so ask before assuming the source tree.
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


_dist = _bundle_root() / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="ui")
