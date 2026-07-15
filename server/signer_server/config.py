"""Environment-driven configuration. Plain os.environ, no config framework."""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    """Populate os.environ from a KEY=VALUE .env file if one exists.

    Real environment variables always win (setdefault), so exported vars and
    test setups are never overridden. Only enough syntax to read .env.example:
    blank lines and #-comments are skipped, surrounding quotes are stripped.
    """
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Config:
    session_dir: Path
    document_dir: Path
    session_ttl_seconds: int
    document_ttl_seconds: int
    p12_path: str | None
    p12_passphrase: str | None
    tsa_url: str | None
    trust_dir: str | None
    max_pdf_mb: int
    strict_ltv: bool

    @property
    def max_pdf_bytes(self) -> int:
        return self.max_pdf_mb * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        default_base = Path(tempfile.gettempdir()) / "signer-server"
        return cls(
            session_dir=Path(os.environ.get("SESSION_DIR", default_base / "sessions")),
            document_dir=Path(os.environ.get("DOCUMENT_DIR", default_base / "documents")),
            session_ttl_seconds=int(os.environ.get("SESSION_TTL_SECONDS", "900")),
            document_ttl_seconds=int(os.environ.get("DOCUMENT_TTL_SECONDS", "3600")),
            p12_path=os.environ.get("P12_PATH"),
            p12_passphrase=os.environ.get("P12_PASSPHRASE"),
            tsa_url=os.environ.get("TSA_URL"),
            trust_dir=os.environ.get("TRUST_DIR"),
            max_pdf_mb=int(os.environ.get("MAX_PDF_MB", "50")),
            # Keep the CRLs a chain needs so B-LT/B-LTA/CCA read as LTV enabled
            # (larger files). Set STRICT_LTV=false for OCSP-first sizing instead.
            strict_ltv=os.environ.get("STRICT_LTV", "true").strip().lower()
            not in ("false", "0", "no", "off"),
        )
