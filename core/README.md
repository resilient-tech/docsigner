# docsigner-core

Digital signing for Python, on top of [pyHanko](https://github.com/MatthiasValvekens/pyHanko).

What it adds: **interrupted signing sessions** — sign a hash now, embed the
signature later — plus PAdES / CAdES / XAdES assembly, LTV and revocation
embedding, PDF/A detection, appearance stamps, and validation.

The interrupted session is the point. It lets the private key stay wherever it
lives — a USB token, an HSM, a browser — while the PDF work happens somewhere
else entirely.

```bash
pip install docsigner-core
pip install "docsigner-core[render]"   # adds PDF rasterization for placement UIs
```

Python 3.10+, pure Python, Apache-2.0.

## Sign with a key you hold

```python
from docsigner_core import sign_with_p12

signed = sign_with_p12(pdf_bytes, "key.p12", passphrase, options)
```

## Sign with a key you don't

Start the session, get a hash, sign it however you like, then complete:

```python
from docsigner_core import SigningSession

state, to_sign, alg = SigningSession.start(pdf_bytes, cert_der, options)
signature = sign_somehow(to_sign)          # token, HSM, remote signer
signed = SigningSession.complete(state, signature)
```

`state` is JSON-safe bytes (`state.to_bytes()` / `SessionState.from_bytes(...)`),
so `start` and `complete` can run in different processes, or on different
machines, minutes apart.

Also exported: `validate`, `Profile`, `make_timestamper`,
`build_validation_context`, `render_page`, `page_size`, `placement_box`,
`SignerError`.

## Fonts for signature stamps

Five handwriting faces and one text face ship inside the package, so a stamp
renders the same wherever it is installed — no reliance on a server having a
script font.

`appearance.font` is a whitelist, because in a server it arrives from an HTTP
request. To add your own:

```python
from docsigner_core.appearance import register_fonts

register_fonts("~/.config/myapp/fonts")   # each .ttf/.otf stem becomes a slug
```

Call it once at startup. Without it, no request can reach a file outside the
bundled six.

## Documentation

| | |
|---|---|
| How signing works, with a flow chart | [docs/core.md](https://github.com/resilient-tech/docsigner/blob/HEAD/docs/core.md) |
| Options, profiles and error codes, frozen | [CONTRACTS.md](https://github.com/resilient-tech/docsigner/blob/HEAD/CONTRACTS.md) |
| The rest of DocSigner | [the repository](https://github.com/resilient-tech/docsigner) |

This is a library, not an application. The DocSigner server, token host, desktop
app and Frappe integration all import it.

---

## Working on it

From a clone of the repo:

```bash
pip install -e ./core
pip install -r requirements-dev.txt
pytest core/tests
```

No hardware needed: token signing is exercised against a fake PKCS#11 layer that
does real RSA math.

Releases are built and published from the repo —
[docs/releasing.md](https://github.com/resilient-tech/docsigner/blob/HEAD/docs/releasing.md).
