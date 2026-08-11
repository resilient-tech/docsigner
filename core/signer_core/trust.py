"""Trust anchors and timestamp clients from deployment configuration."""

from pathlib import Path

from pyhanko.keys.pemder import load_certs_from_pemder_data
from pyhanko.sign.timestamps import HTTPTimeStamper
from pyhanko_certvalidator import ValidationContext

from .errors import SignerError

CERT_SUFFIXES = (".pem", ".crt", ".cer", ".der")


def load_trust_certs(trust_dir) -> list:
    """Every certificate in a folder and below it.

    Skips anything under "archive". Expired roots wait there; move one back up
    to check a document signed under it.
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
    """Who we trust. No folder means we trust nobody, so everything reads untrusted.

    Only self-signed certificates count as roots. A sub-CA mistaken for a root
    would stop the walk early and miss the real root.

    Use revocation_mode "require" when building a long-term signature: the
    default tolerates gaps, and a gap means Adobe will not call it LTV.
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


# Free public clocks. A request picks one by name, never by URL: letting a
# client name any URL would move a trust decision off the server.
KNOWN_TSAS = {
    "digicert": "http://timestamp.digicert.com",
    "sectigo": "http://timestamp.sectigo.com",
    "certum": "http://time.certum.pl",
    "entrust": "http://timestamp.entrust.net/TSS/RFC3161sha2TS",
    "ssl-com": "http://ts.ssl.com",
}


def resolve_tsa_url(name, default_url=None):
    """Name to URL. Empty means the configured default.

    An unknown name raises rather than falling back, so nobody who picked a
    clock quietly gets a different one.
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


def make_timestamper(tsa_url=None, auth=None, bearer=None):
    """The thing that stamps the time.

    Public clocks answer anyone. Indian ones sell timestamps and want a login,
    so both ways in are here: `auth` is (user, password), `bearer` is a token.
    """
    if not tsa_url:
        return None
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else None
    return HTTPTimeStamper(tsa_url, auth=auth, headers=headers)
