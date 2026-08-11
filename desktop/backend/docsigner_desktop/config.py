"""Where to get the time from, and who to trust.

Override with DOCSIGNER_TSA_URL and DOCSIGNER_TRUST_DIR. If the repo's trust/
folder sits nearby it gets picked up on its own.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from docsigner_core import Profile, build_validation_context, make_timestamper

from .store import DATA_DIR

TSA_URL = os.environ.get("DOCSIGNER_TSA_URL") or "http://timestamp.digicert.com"
LOG_FILE = DATA_DIR / "docsigner-desktop.log"


def setup_logging() -> None:
    """Write to a rolling log file, so a user can send us what broke."""
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
        # Where a packaged build unpacks the bundled trust/ folder.
        bundled = Path(sys._MEIPASS) / "trust"
        return str(bundled) if bundled.exists() else None
    # desktop/backend/docsigner_desktop/config.py -> parents[3] is the repo root.
    guess = Path(__file__).resolve().parents[3] / "trust"
    return str(guess) if guess.exists() else None


TRUST_DIR = _autodetect_trust()


def context_for(standard: str, tsa_url: str | None = None):
    """The clock and the trust list this standard needs. Both None for plain B-B."""
    profile = Profile.parse(standard)
    ts = make_timestamper(tsa_url or TSA_URL) if profile.needs_timestamp else None
    vc = None
    if profile.needs_revocation_info or profile.is_cca:
        vc = build_validation_context(TRUST_DIR, allow_fetching=True, revocation_mode="require")
    return ts, vc


def info() -> dict:
    return {"tsaUrl": TSA_URL, "trustConfigured": TRUST_DIR is not None, "logPath": str(LOG_FILE)}
