"""Bits every signing flow needs. Lives here so no flow reaches into another."""

import base64
import dataclasses
import hashlib
import json

from asn1crypto import x509 as asn1_x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.hazmat.primitives.serialization import load_der_public_key
from pyhanko.sign import signers

from .errors import SignerError

# Hole we leave for a signature we do not have yet. Fits RSA-4096.
PLACEHOLDER_SIG_SIZE = 512


def encode_state(state, bytes_fields: tuple, *, kind: str | None = None) -> bytes:
    """State to JSON bytes. Byte fields go base64, `kind` tags what it is."""
    data = dataclasses.asdict(state)
    if kind:
        data["kind"] = kind
    for field in bytes_fields:
        data[field] = base64.b64encode(data[field]).decode("ascii")
    return json.dumps(data).encode("utf-8")


def decode_state(raw: bytes, bytes_fields: tuple, *, kind: str | None = None) -> dict:
    """Back to a kwargs dict. Refuses the wrong kind of session blob."""
    data = json.loads(raw.decode("utf-8"))
    stored = data.pop("kind", None)
    if kind is not None and stored is not None and stored != kind:
        raise SignerError("SESSION_NOT_FOUND", f"no such {kind} session")
    for field in bytes_fields:
        data[field] = base64.b64decode(data[field])
    return data


def parse_cert(cert_der: bytes) -> asn1_x509.Certificate:
    """DER bytes -> certificate; only RSA and EC keys allowed."""
    try:
        cert = asn1_x509.Certificate.load(cert_der)
        key_algorithm = cert.public_key.algorithm
    except Exception:
        raise SignerError("CERT_INVALID", "certificate is not valid DER") from None
    if key_algorithm not in ("rsa", "ec"):
        raise SignerError(
            "CERT_INVALID",
            f"unsupported key type {key_algorithm!r}; RSA and EC are supported",
        )
    return cert


def verify_signature(signer_cert, signature, signed_attrs_der, md_algorithm):
    """Reject garbage before it gets baked into the PDF."""
    public_key = load_der_public_key(signer_cert.public_key.dump())
    digest = hashlib.new(md_algorithm, signed_attrs_der).digest()
    prehashed = Prehashed(getattr(hashes, md_algorithm.upper())())
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, digest, padding.PKCS1v15(), prehashed)
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, digest, ec.ECDSA(prehashed))
        else:
            raise SignerError("CERT_INVALID", "unsupported key type")
    except InvalidSignature:
        raise SignerError(
            "SIGNATURE_INVALID",
            "signature does not verify against the supplied certificate",
        ) from None


def load_p12_signer(p12_path, passphrase):
    """Load the server's own .p12 key."""
    if isinstance(passphrase, str):
        passphrase = passphrase.encode("utf-8")
    try:
        signer = signers.SimpleSigner.load_pkcs12(p12_path, passphrase=passphrase)
    except Exception:
        signer = None
    if signer is None:
        raise SignerError(
            "INTERNAL", "could not load the server signing key (check P12_PATH/P12_PASSPHRASE)"
        )
    return signer
