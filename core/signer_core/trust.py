"""Trust anchors and timestamp clients from deployment configuration."""

from pathlib import Path

from pyhanko.keys.pemder import load_certs_from_pemder_data
from pyhanko.sign.timestamps import HTTPTimeStamper
from pyhanko_certvalidator import ValidationContext

from .errors import SignerError

CERT_SUFFIXES = (".pem", ".crt", ".cer", ".der")


def load_trust_certs(trust_dir) -> list:
    """Load every PEM/DER certificate under a directory, recursively.

    Subdirectories group certificates (by country, by purpose: in/, tsa/, ...).
    Anything under a directory named "archive" is skipped; expired roots live
    there so old documents can still be validated by moving them back in.
    """
    base = Path(trust_dir)
    certs = []
    for path in sorted(base.rglob("*")):
        if not (path.is_file() and path.suffix.lower() in CERT_SUFFIXES):
            continue
        if "archive" in path.relative_to(base).parts[:-1]:
            continue
        certs.extend(load_certs_from_pemder_data(path.read_bytes()))
    return certs


def build_validation_context(
    trust_dir=None, allow_fetching=False, revocation_mode="soft-fail"
) -> ValidationContext:
    """No trust dir means an empty trust set: signatures come back trusted=False.

    Only self-signed certificates in the directory are treated as trust anchors;
    intermediates (a sub-CA, an issuing CA) go into the path-building pool. That
    keeps a sub-CA from being mistaken for a root, which would anchor validation
    early and cut LTV revocation gathering short of the real root.

    revocation_mode "require" makes LTV augmentation gather revocation for every
    certificate in the chain (signer and timestamp). The default "soft-fail"
    tolerates gaps, which is right for read-only validation but leaves a B-LT
    DSS incomplete: Adobe then reports the signature as not LTV enabled.
    """
    certs = load_trust_certs(trust_dir) if trust_dir else []
    roots = [c for c in certs if c.subject == c.issuer]
    intermediates = [c for c in certs if c.subject != c.issuer]
    return ValidationContext(
        trust_roots=roots,
        other_certs=intermediates,
        allow_fetching=allow_fetching,
        revocation_mode=revocation_mode,
    )


# Public RFC 3161 endpoints that answer without an account. A request picks
# one by name (options.tsa); arbitrary URLs from clients are refused so the
# deployment's trust decisions stay server-side. For LTV profiles the chosen
# TSA's root must sit in TRUST_DIR (trust/tsa/, fed by scripts/fetch_trust_roots.py).
KNOWN_TSAS = {
    "digicert": "http://timestamp.digicert.com",
    "sectigo": "http://timestamp.sectigo.com",
    "certum": "http://time.certum.pl",
    "entrust": "http://timestamp.entrust.net/TSS/RFC3161sha2TS",
    "ssl-com": "http://ts.ssl.com",
}


def resolve_tsa_url(name, default_url=None):
    """Map a client-supplied TSA name to its URL; None/empty means the default.

    Unknown names raise instead of falling back, so a tester who picked a TSA
    is never silently timestamped by a different one.
    """
    if not name:
        return default_url
    try:
        return KNOWN_TSAS[name]
    except KeyError:
        raise SignerError(
            "PROFILE_UNSUPPORTED",
            f"unknown timestamp authority {name!r}; expected one of "
            + ", ".join(sorted(KNOWN_TSAS)),
        ) from None


def make_timestamper(tsa_url=None):
    return HTTPTimeStamper(tsa_url) if tsa_url else None
