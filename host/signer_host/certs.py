"""Turn a certificate into the JSON fields the contract wants.

Shared by both signing backends: PKCS#11 tokens (pkcs11_ops.py) and the OS
store (os_store.py). Kept here so neither backend reaches into the other.
"""

import base64
import hashlib
from datetime import timezone

from asn1crypto import x509

from .errors import HostError

DIGEST_ALGORITHMS = ("sha256", "sha384", "sha512")

# OID friendly-name -> short name (CN, O, ...).
_NAME_SHORT = {
    "common_name": "CN",
    "organization_name": "O",
    "organizational_unit_name": "OU",
    "country_name": "C",
    "state_or_province_name": "ST",
    "locality_name": "L",
    "email_address": "E",
    "serial_number": "SERIALNUMBER",
    "domain_component": "DC",
    "title": "T",
    "given_name": "G",
    "surname": "SN",
    "pseudonym": "PSEUDONYM",
    "street_address": "STREET",
    "postal_code": "POSTALCODE",
}

_KEY_TYPES = {"rsa": "RSA", "rsassa_pss": "RSA", "ec": "EC"}

# X.509 key-usage flag -> contract field name. Mirrors another vendor's KeyUsagesModel
# so pages can filter signing certs on multi-cert tokens.
_KEY_USAGE_FIELDS = {
    "digital_signature": "digitalSignature",
    "non_repudiation": "nonRepudiation",
    "key_encipherment": "keyEncipherment",
    "data_encipherment": "dataEncipherment",
    "key_agreement": "keyAgreement",
    "key_cert_sign": "keyCertSign",
    "crl_sign": "crlSign",
}


def iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def name_to_string(name):
    """asn1crypto Name -> 'CN=..., O=..., C=...' (most specific first)."""
    parts = []
    for rdn in reversed(list(name.chosen)):
        for type_value in rdn:
            key = type_value["type"].native
            value = type_value["value"].native
            if not isinstance(value, str):
                value = str(value)
            parts.append("%s=%s" % (_NAME_SHORT.get(key, key), value))
    return ", ".join(parts)


def key_usage(cert):
    """Key-usage booleans; all false when the extension is absent or unreadable."""
    try:
        usage_set = cert.key_usage_value.native if cert.key_usage_value else set()
    except Exception:
        usage_set = set()
    return {field: flag in usage_set for flag, field in _KEY_USAGE_FIELDS.items()}


def cert_info(der):
    """Contract fields for one DER cert (tokenLabel/moduleName added by callers)."""
    cert = x509.Certificate.load(der)
    validity = cert["tbs_certificate"]["validity"]
    algorithm = cert.public_key.algorithm
    return {
        "thumbprint": hashlib.sha1(der).hexdigest(),
        "certificate": base64.b64encode(der).decode("ascii"),
        "subject": name_to_string(cert.subject),
        "issuer": name_to_string(cert.issuer),
        "validFrom": iso_utc(validity["not_before"].native),
        "validTo": iso_utc(validity["not_after"].native),
        "keyType": _KEY_TYPES.get(algorithm, algorithm.upper()),
        "keyUsage": key_usage(cert),
    }


def ecdsa_raw_to_der(raw):
    """Raw r||s ECDSA signature -> DER ECDSA-Sig-Value."""
    from asn1crypto import algos

    if not raw or len(raw) % 2:
        raise HostError("INTERNAL", "malformed raw ECDSA signature (%d bytes)" % len(raw))
    half = len(raw) // 2
    r = int.from_bytes(raw[:half], "big")
    s = int.from_bytes(raw[half:], "big")
    return algos.DSASignature({"r": r, "s": s}).dump()
