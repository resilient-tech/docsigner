"""Download and organise the trust store under trust/.

Layout: one folder per country or purpose (in/, br/, us/, tsa/). Expired
certificates land in trust/archive/<folder>/ so they stay out of the anchors
the server loads, while remaining available for validating old documents.

Run from the repo root:

    python scripts/fetch_trust_roots.py

Safe to re-run: files are overwritten with fresh copies, nothing else in the
tree is touched. Sources are the CAs' own repositories. The EU is deliberately
absent here; its trust comes as per-country signed XML lists (EUTL, ETSI TS
119 612), which need a parser rather than a folder of files.
"""

import base64
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import serialization

TRUST = Path(__file__).resolve().parents[1] / "trust"

# folder -> [(file stem, url)]
SOURCES = {
    # India: CCA roots anchor every licensed CA (Capricorn, eMudhra, Sify, ...).
    # The Capricorn intermediates are optional speed-ups; AIA fetching finds
    # them anyway when absent.
    "in": [
        ("CCA-India-2022", "https://www.cca.gov.in/cca/sites/default/files/files/CCAIndia2022.cer"),
        ("CCA-India-2022-SPL", "https://www.cca.gov.in/cca/sites/default/files/files/CCAIndia2022SPL.cer"),
        ("CCA-India-2015", "https://www.cca.gov.in/cca/sites/default/files/files/CCAIndia2015.cer"),
        ("CCA-India-2014", "https://www.cca.gov.in/cca/sites/default/files/files/CCAIndia2014.cer"),
        ("CCA-India-2011", "https://www.cca.gov.in/cca/sites/default/files/files/cca%20india%202011.cer"),
        ("CCA-India-2007", "https://www.cca.gov.in/cca/sites/default/files/files/cca%20india%202007.cer"),
        ("Capricorn-CA-2022", "http://www.certificate.digital/repository/CapricornCA2022.cer"),
        ("Capricorn-Sub-CA-for-Individual-DSC-2022", "http://www.certificate.digital/repository/CapricornSubCAforIndividualDSC2022.cer"),
        ("Capricorn-Sub-CA-for-Organisation-DSC-2022", "http://www.certificate.digital/repository/CapricornSubCAforOrganisationDSC2022.cer"),
    ],
    # Brazil: ICP-Brasil roots (MP 2.200-2 / Lei 14.063 hierarchy).
    "br": [
        ("ICP-Brasil-v5", "http://acraiz.icpbrasil.gov.br/ICP-Brasilv5.crt"),
        ("ICP-Brasil-v10", "http://acraiz.icpbrasil.gov.br/ICP-Brasilv10.crt"),
        ("ICP-Brasil-v11", "http://acraiz.icpbrasil.gov.br/ICP-Brasilv11.crt"),
    ],
    # US: Federal PKI trust anchor (federal documents; commercial US signing
    # is technology-neutral and rides on AATL instead).
    "us": [
        ("FPKI-Federal-Common-Policy-G2", "http://repo.fpki.gov/fcpca/fcpcag2.crt"),
    ],
    # Timestamp authorities configured in TSA_URL. The TSA's intermediates
    # arrive inside each timestamp token; only the roots are needed here.
    "tsa": [
        ("DigiCert-Trusted-Root-G4", "https://cacerts.digicert.com/DigiCertTrustedRootG4.crt"),
        ("DigiCert-Assured-ID-Root-CA", "https://cacerts.digicert.com/DigiCertAssuredIDRootCA.crt"),
    ],
}


def parse_cert(data: bytes) -> x509.Certificate:
    """DER, PEM (CRLF or stray blank lines), or bare base64: CA repositories
    serve all three."""
    try:
        return x509.load_der_x509_certificate(data)
    except ValueError:
        pass
    try:
        text = data.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        raise ValueError("neither DER nor text")
    clean = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if "BEGIN CERTIFICATE" in clean:
        return x509.load_pem_x509_certificate((clean + "\n").encode())
    return x509.load_der_x509_certificate(base64.b64decode(clean, validate=False))


def main() -> int:
    now = datetime.now(timezone.utc)
    failures = 0
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for folder, entries in SOURCES.items():
            for stem, url in entries:
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    cert = parse_cert(response.content.strip())
                except Exception as exc:
                    failures += 1
                    print(f"FAIL  {folder}/{stem}: {type(exc).__name__} {str(exc)[:80]}")
                    continue
                expired = cert.not_valid_after_utc < now
                root = cert.subject == cert.issuer
                target = (TRUST / "archive" / folder) if expired else (TRUST / folder)
                target.mkdir(parents=True, exist_ok=True)
                name = stem + (".root.pem" if root else ".pem")
                (target / name).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                state = f"expired {cert.not_valid_after_utc:%Y-%m}" if expired else f"until {cert.not_valid_after_utc:%Y-%m}"
                print(f"ok    {target.relative_to(TRUST.parent)}/{name}  ({state})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
