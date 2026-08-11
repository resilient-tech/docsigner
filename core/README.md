# signer-core

The Python signing library the rest of DocSigner is built on. pyHanko does the
PDF work underneath; this package adds interrupted signing sessions (sign a hash
now, embed the signature later), PAdES / CAdES / XAdES assembly, LTV and
revocation embedding, PDF/A detection, appearance stamps, and validation.

It is a library, not an app. The server, host, desktop app, and the Frappe
integration all import it.

New here? Read [`../docs/core.md`](../docs/core.md) first: plain words, a flow
chart of how signing works, and the module map.

## Install (development)

From the repo root:

```bash
pip install -e ./core          # add [render] for rendering.py
```

## Use it

Two entry points cover most cases. A one-shot signature with a server-held key:

```python
from signer_core import sign_with_p12

signed = sign_with_p12(pdf_bytes, "key.p12", passphrase, options)
```

An interrupted session, where the hash is signed elsewhere (a token, a browser):

```python
from signer_core import SigningSession

state, to_sign, alg = SigningSession.start(pdf_bytes, cert_der, options)
signature = sign_somehow(to_sign)          # token, HSM, remote signer
signed = SigningSession.complete(state, signature)
```

`state` is JSON-safe bytes (`state.to_bytes()` / `SessionState.from_bytes(...)`),
so `start` and `complete` can run in different processes.

Options, profiles and error codes are frozen in
[`../CONTRACTS.md`](../CONTRACTS.md).

## Fonts

Five handwriting faces and one text face ship inside the package
(`signer_core/fonts/`, bundled through `package-data`), so a stamp renders the
same wherever the library is installed. Details in
[`signer_core/fonts/README.md`](signer_core/fonts/README.md).

`appearance.font` is a whitelist, because in a server it arrives from an HTTP
request. An application that owns its own font folder adds to that whitelist:

```python
from signer_core.appearance import register_fonts

register_fonts("~/.config/myapp/fonts")   # each .ttf/.otf stem becomes a slug
```

Call it once at startup. The reference server never does, so no request can
reach a file outside the bundled five.

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
