# signer-core

The Python signing library the rest of OpenSigner is built on. pyHanko does the
PDF work underneath; this package adds interrupted signing sessions (sign a hash
now, embed the signature later), PAdES / CAdES / XAdES assembly, LTV and
revocation embedding, PDF/A detection, appearance stamps, and validation.

It is a library, not an app. The server, host, desktop app, and the Frappe
integration all import it.

## Install (development)

From the repo root:

```bash
pip install -e ./core
```

## Use it

Two entry points cover most cases. A one-shot signature with a server-held key:

```python
from signer_core.server_signer import sign_with_p12

signed = sign_with_p12(pdf_bytes, "key.p12", passphrase, options)
```

An interrupted session, where the hash is signed elsewhere (a token, a browser):

```python
from signer_core.session import SigningSession

state, to_sign, alg = SigningSession.start(pdf_bytes, cert_der, options)
signature = sign_somehow(to_sign)          # token, HSM, remote signer
signed = SigningSession.complete(state, signature)
```

The module map: `session.py` and `server_signer.py` (signing), `profiles.py`
(PAdES/CAdES profiles), `ltv.py` and `trust.py` and `validation.py` (revocation,
trust anchors, verification), `appearance.py` (visible stamps), `cades.py` /
`xades.py` (detached and XML), `pdfa.py` (conformance detection), `rendering.py`
(page rasterization and placement math, needs the optional `[render]` extra). The
signing protocol and error codes are frozen in [`../CONTRACTS.md`](../CONTRACTS.md).

## Fonts

The handwriting and text faces for appearance stamps ship inside the package
(`signer_core/fonts/`, bundled through `package-data`), so a stamp renders the
same wherever the library is installed. Details in
[`signer_core/fonts/README.md`](signer_core/fonts/README.md).

## Pack it

Not published to PyPI. Everything in this repo consumes it by path
(`pip install -e ./core`), and the Frappe app pins it as a pip dependency. To
build a wheel and sdist anyway:

```bash
pip install build
python -m build core        # -> core/dist/signer_core-*.whl, *.tar.gz
```

## Tests

```bash
pip install -e ./core
pip install -r requirements-dev.txt
pytest core/tests
```

No hardware needed: token signing is exercised against a fake PKCS#11 layer that
does real RSA math.
