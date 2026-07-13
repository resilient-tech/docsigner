"""FastAPI routes. In dev the Vite server proxies /api here; in prod this also
serves the built frontend from ../frontend/dist."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import certs, config, picker, render, signing, store
from .models import Settings, SignRequest

app = FastAPI(title="OpenSigner Desktop")
config.setup_logging()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/config")
def get_config() -> dict:
    return config.info()


@app.get("/api/identities")
def identities() -> list[dict]:
    return certs.list_identities(store.KEYS_DIR)


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
        return render.render_page(str(Path(path).expanduser()), index, width)
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


_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="ui")
