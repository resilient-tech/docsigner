"""Settings, straight from environment variables. No config framework."""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    """Read a .env file, if there is one.

    A real environment variable always wins. Handles blank lines, # comments
    and quotes, and nothing fancier.
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


def _split_pair(value: str | None) -> tuple[str, str] | None:
    """Split "user:password". First colon only, so passwords may contain colons."""
    if not value:
        return None
    user, sep, password = value.partition(":")
    return (user, password) if sep else None


@dataclass(frozen=True)
class Config:
    session_dir: Path
    document_dir: Path
    session_ttl_seconds: int
    document_ttl_seconds: int
    p12_path: str | None
    p12_passphrase: str | None
    tsa_url: str | None
    tsa_auth: tuple[str, str] | None
    tsa_bearer: str | None
    trust_dir: str | None
    policy_dir: str | None
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
            tsa_auth=_split_pair(os.environ.get("TSA_AUTH")),
            tsa_bearer=os.environ.get("TSA_BEARER"),
            trust_dir=os.environ.get("TRUST_DIR"),
            policy_dir=os.environ.get("POLICY_DIR"),
            max_pdf_mb=int(os.environ.get("MAX_PDF_MB", "50")),
            # Keep every proof, so Adobe shows the LTV badge. Bigger files.
            # STRICT_LTV=false trades the badge for size.
            strict_ltv=os.environ.get("STRICT_LTV", "true").strip().lower()
            not in ("false", "0", "no", "off"),
        )
