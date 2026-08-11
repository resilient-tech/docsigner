"""Settings and saved stamp styles, so the app remembers between launches."""

import os
from pathlib import Path

from .models import AppearanceProfile, Settings

DATA_DIR = Path(os.environ.get("DOCSIGNER_DATA", str(Path.home() / ".config" / "docsigner-desktop")))
SETTINGS_FILE = DATA_DIR / "settings.json"
KEYS_DIR = DATA_DIR / "signing-keys"
FONTS_DIR = DATA_DIR / "fonts"  # handwriting faces the user uploaded (see fonts.py)

DEFAULT_PROFILES = [
    AppearanceProfile(id="handwritten-date", name="Handwritten + Date", style="handwritten",
                      font="great-vibes", show_name=True, show_date=True),
    AppearanceProfile(id="reason-location", name="Reason + Location", style="handwritten",
                      font="caveat", show_name=True, show_date=True, show_reason=True, show_location=True),
    AppearanceProfile(id="standard-text", name="Standard text", style="text",
                      show_name=True, show_date=True),
]


def load_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SETTINGS_FILE.exists():
        try:
            s = Settings.model_validate_json(SETTINGS_FILE.read_text())
        except Exception:
            s = Settings()
    else:
        s = Settings()
    if not s.profiles:
        s.profiles = [p.model_copy() for p in DEFAULT_PROFILES]
    if not s.profile_id:
        s.profile_id = s.profiles[0].id
    return s


def save_settings(s: Settings) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(s.model_dump_json(indent=2))
