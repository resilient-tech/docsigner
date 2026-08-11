"""Sign XML. Server key only.

The library we use wants the key in hand, so a token cannot drive this. Doing
it with a token means rebuilding XML signing around a hash, and nobody has
asked yet. Callers get a clear error.
"""

from pathlib import Path

from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

from .errors import SignerError


def sign_xml_with_p12(xml_bytes: bytes, p12_path, passphrase, options=None) -> bytes:
    """Sign an XML document (enveloped XAdES-B) with the server-held key."""
    from signxml.xades import XAdESSigner  # heavy import, only on use

    try:
        key, cert, extra = pkcs12.load_key_and_certificates(
            Path(p12_path).read_bytes(),
            passphrase.encode() if passphrase else None,
        )
    except Exception:
        raise SignerError(
            "INTERNAL", "could not load the server signing key (check P12_PATH/P12_PASSPHRASE)"
        ) from None

    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise SignerError("DOCUMENT_INVALID", f"not well-formed XML: {exc}") from None

    signed = XAdESSigner().sign(root, key=key, cert=[cert, *(extra or [])])
    return etree.tostring(signed, xml_declaration=True, encoding="UTF-8")
