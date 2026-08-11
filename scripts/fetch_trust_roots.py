"""Fetch the certificates we trust, straight from the CAs.

One folder per country or job (in/, br/, us/, tsa/). Expired ones go to
archive/, out of the way but still there for checking old documents.

    python scripts/fetch_trust_roots.py     # from the repo root

Safe to re-run. The EU is missing on purpose: its trust arrives as signed XML
lists that need a parser, not a folder of files.
"""

import base64
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import serialization

TRUST = Path(__file__).resolve().parents[1] / "trust"

_CCA_FILES = "https://www.cca.gov.in/cca/sites/default/files/files/"

# Every licensed Indian CA, from CCA's own list. These sit in the middle of a
# chain, not at the top. Keeping them here saves a network trip at signing
# time; one that is missing still works, just slower.
_LICENSED_CAS_2022 = [
    ("SafeScrypt-CA-2022", "Sify%20Safecrypt%20CA%202022.cer"),
    ("eMudhra-CA-2022", "e-Mudhra%20CA%202022.cer"),
    ("RajComp-CA-2022", "RajComp%20CA%202022.cer"),
    ("Verasys-CA-2022", "Verasys%20CA%202022.cer"),
    ("XtraTrust-CA-2022", "XtratrustCA2022.cer"),
    ("IDRBT-CA-2022", "IDRBT%20CA%202022.cer"),
    ("IDSign-CA-2022", "IDSign_CA_2022.cer"),
    ("nCode-Solutions-CA-2022", "nCode%20Solutions%20CA%202022.cer"),
    ("PantaSign-CA-2022", "PantaSign_CA_2022.cer"),
    ("Capricorn-CA-2022", "Capricorn%20CA%202022.cer"),
    ("ProDigiSign-CA-2022", "ProDigiSign-CA-2022.cer"),
    ("SignX-CA-2022", "SignX%20CA%202022.cer"),
    ("CDAC-CA-2022", "CDAC%20CA.cer"),
    ("CDSL-Ventures-CA-2022", "CDSL%20Ventures%20Limited%20CA.cer"),
    ("Protean-eGov-CA-2022", "Protean%20eGov%20CA.cer"),
    ("Care4Sign-CA-2022", "Care4sign-CA-2022.cer"),
    ("IGCAR-CA-2022", "IGCAR%20CA%202022.cer"),
    ("JPSL-CA-2022", "JPSL_%20CA_%202022%20.cer"),
    ("CDSL-CA-2022", "CDSL_CA_2022.cer"),
    ("Speed-Sign-CA-2022", "Speed_Sign_2022.cer"),
    ("CSC-CA-2022", "CSC_CA_2022.cer"),
]

# folder -> [(file stem, url)]
SOURCES = {
    # India: CCA roots anchor every licensed CA; the licensed-CA certificates
    # and Capricorn's sub-CAs ride along as locally held intermediates.
    "in": [
        ("CCA-India-2022", _CCA_FILES + "CCAIndia2022.cer"),
        ("CCA-India-2022-SPL", _CCA_FILES + "CCAIndia2022SPL.cer"),
        ("CCA-India-2015", _CCA_FILES + "CCAIndia2015.cer"),
        ("CCA-India-2014", _CCA_FILES + "CCAIndia2014.cer"),
        ("CCA-India-2011", _CCA_FILES + "cca%20india%202011.cer"),
        ("CCA-India-2007", _CCA_FILES + "cca%20india%202007.cer"),
        *[(stem, _CCA_FILES + fname) for stem, fname in _LICENSED_CAS_2022],
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
    # Roots for every TSA in the server's registry (signer_core.trust.KNOWN_TSAS).
    # A TSA's intermediates arrive inside each timestamp token; only roots are
    # needed here, and only the LTV profiles consult them.
    "tsa": [
        ("DigiCert-Trusted-Root-G4", "https://cacerts.digicert.com/DigiCertTrustedRootG4.crt"),
        ("DigiCert-Assured-ID-Root-CA", "https://cacerts.digicert.com/DigiCertAssuredIDRootCA.crt"),
        # crt.sectigo.com rejects plain TLS clients; the repo is served over http.
        ("USERTrust-RSA-CA", "http://crt.sectigo.com/USERTrustRSACertificationAuthority.crt"),
        ("Sectigo-Public-Time-Stamping-Root-R46", "http://crt.sectigo.com/SectigoPublicTimeStampingRootR46.crt"),
        ("Certum-Trusted-Network-CA", "https://repository.certum.pl/ctnca.cer"),
        ("Certum-Trusted-Network-CA-2", "https://repository.certum.pl/ctnca2.cer"),
        # SSL.com's HTML repository sits behind a WAF, but the AIA caIssuers URL
        # from its timestamp tokens serves the root certificate directly.
        ("SSLcom-Root-Certification-Authority-RSA", "http://www.ssl.com/repository/SSLcomRootCertificationAuthorityRSA.crt"),
        # Entrust's public TSA is served by Sectigo; its tokens chain to the
        # Sectigo and USERTrust roots already listed above, so it needs no entry.
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
