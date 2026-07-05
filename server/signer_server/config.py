"""Environment-driven configuration. Plain os.environ, no config framework."""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Config:
    session_dir: Path
    document_dir: Path
    session_ttl_seconds: int
    document_ttl_seconds: int
    p12_path: Optional[str]
    p12_passphrase: Optional[str]
    tsa_url: Optional[str]
    trust_dir: Optional[str]
    max_pdf_mb: int

    @property
    def max_pdf_bytes(self) -> int:
        return self.max_pdf_mb * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Config":
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
        )
