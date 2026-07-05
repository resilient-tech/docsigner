"""End-to-end check against a live signer-server on localhost:8000.

Plays the browser + token roles:
  start session -> sign returned hash with an in-memory RSA key
  (byte-identical to what signer-host produces via CKM_RSA_PKCS)
  -> complete -> download -> validate via the API.

Run:  python e2e_http_test.py
"""

import base64
import sys

import httpx

sys.path.insert(0, ".")
from spike_interrupted_signing import make_blank_pdf, make_self_signed_cert

BASE = "http://127.0.0.1:8000/api"


def main():
    key, cert_der = make_self_signed_cert()
    pdf = make_blank_pdf()
    b64 = lambda b: base64.b64encode(b).decode()

    r = httpx.post(
        f"{BASE}/signatures",
        json={
            "document": b64(pdf),
            "certificate": b64(cert_der),
            "options": {
                "profile": "B-B",
                "reason": "e2e test",
                "appearance": {"page": 0, "box": [72, 72, 272, 122]},
            },
        },
        timeout=30,
    )
    r.raise_for_status()
    start = r.json()
    print("start:", {k: start[k] for k in ("session_id", "digest_algorithm")})

    to_sign = base64.b64decode(start["to_sign_hash"])
    assert len(to_sign) == 32, "expected a sha256 digest"

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

    signature = key.sign(to_sign, padding.PKCS1v15(), Prehashed(hashes.SHA256()))

    r = httpx.post(
        f"{BASE}/signatures/{start['session_id']}/complete",
        json={"signature": b64(signature)},
        timeout=30,
    )
    r.raise_for_status()
    done = r.json()
    print("complete:", done)

    r = httpx.get(f"http://127.0.0.1:8000{done['download_url']}", timeout=30)
    r.raise_for_status()
    signed_pdf = r.content
    assert signed_pdf[:5] == b"%PDF-" and len(signed_pdf) > len(pdf)
    print(f"downloaded signed PDF: {len(signed_pdf)} bytes")

    r = httpx.post(f"{BASE}/validate", json={"document": b64(signed_pdf)}, timeout=30)
    r.raise_for_status()
    report = r.json()
    print("validate:", report)
    sig = report["signatures"][0]
    assert sig["valid"] and sig["intact"], "signature not valid/intact"

    print("\nE2E OK: live server round trip produced a valid signed PDF")


if __name__ == "__main__":
    main()
