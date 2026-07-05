"""Trust anchors and timestamp clients from deployment configuration."""

from pathlib import Path

from pyhanko.keys.pemder import load_certs_from_pemder_data
from pyhanko.sign.timestamps import HTTPTimeStamper
from pyhanko_certvalidator import ValidationContext

CERT_SUFFIXES = (".pem", ".crt", ".cer", ".der")


def load_trust_certs(trust_dir) -> list:
    """Load every PEM/DER certificate file found in a directory."""
    certs = []
    for path in sorted(Path(trust_dir).iterdir()):
        if path.is_file() and path.suffix.lower() in CERT_SUFFIXES:
            certs.extend(load_certs_from_pemder_data(path.read_bytes()))
    return certs


def build_validation_context(trust_dir=None, allow_fetching=False) -> ValidationContext:
    """No trust dir means an empty trust set: signatures come back trusted=False."""
    trust_roots = load_trust_certs(trust_dir) if trust_dir else []
    return ValidationContext(trust_roots=trust_roots, allow_fetching=allow_fetching)


def make_timestamper(tsa_url=None):
    return HTTPTimeStamper(tsa_url) if tsa_url else None
