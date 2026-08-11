"""Timestamp authority and trust anchors, the same story as the Frappe
integration: B-T adds an RFC 3161 timestamp; B-LT and the CCA profiles embed
revocation data gathered against the trust anchors.

Override with DOCSIGNER_TSA_URL and DOCSIGNER_TRUST_DIR. If the DocSigner
repo's bundled trust/ store sits nearby it is picked up automatically.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from signer_core import Profile, build_validation_context, make_timestamper

from .store import DATA_DIR

TSA_URL = os.environ.get("DOCSIGNER_TSA_URL") or "http://timestamp.digicert.com"
LOG_FILE = DATA_DIR / "docsigner-desktop.log"


def setup_logging() -> None:
    """Log to a rotating file so failures (with tracebacks) can be shared."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("docsigner_desktop")
    logger.setLevel(logging.INFO)
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)


def _autodetect_trust() -> str | None:
    env = os.environ.get("DOCSIGNER_TRUST_DIR")
    if env:
        return env
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks bundled trust/ (see the spec's datas) here.
        bundled = Path(sys._MEIPASS) / "trust"
        return str(bundled) if bundled.exists() else None
    # desktop/backend/docsigner_desktop/config.py -> parents[3] is the repo root.
    guess = Path(__file__).resolve().parents[3] / "trust"
    return str(guess) if guess.exists() else None


TRUST_DIR = _autodetect_trust()


def context_for(standard: str, tsa_url: str | None = None):
    """Return (timestamper, validation_context) for a standard; (None, None) for B-B.

    tsa_url overrides the default TSA for this batch (the settings-page value);
    an empty/None value falls back to DOCSIGNER_TSA_URL / the built-in default.
    """
    profile = Profile.parse(standard)
    ts = make_timestamper(tsa_url or TSA_URL) if profile.needs_timestamp else None
    vc = None
    if profile.needs_revocation_info or profile.is_cca:
        vc = build_validation_context(TRUST_DIR, allow_fetching=True, revocation_mode="require")
    return ts, vc


def info() -> dict:
    return {"tsaUrl": TSA_URL, "trustConfigured": TRUST_DIR is not None, "logPath": str(LOG_FILE)}
