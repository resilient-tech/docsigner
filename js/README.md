# docsigner

Sign PDFs in the browser with a DSC token. One file, no dependencies.

The page never sees the private key. This library talks to the DocSigner browser
extension, which talks to a native host, which reads the token — so a web page
can list certificates and get hashes signed without the key ever leaving the
device.

```bash
npm install docsigner
```

Or copy `docsigner.js` into your site. It is an ES module: import it in a
bundler or straight from a `<script type="module">` tag. There is nothing to
build.

## Use it

```html
<script type="module">
  import { DocSigner } from "./docsigner.js";
  const signer = new DocSigner();
  await signer.init();
  const certs = await signer.listCertificates();
  const { signatures } = await signer.signHash({
    thumbprint: certs[0].thumbprint,
    hashes: [toSignHash],
    digestAlgorithm: "sha256",
  });
</script>
```

Signing needs the extension and the native host installed on the user's
machine. Both are on the
[releases page](https://github.com/resilient-tech/docsigner/releases).

## Check before you prompt

`status()` says which of the two pieces are there. It prompts nobody — no
consent popup, no token access — so it is the call to gate a Sign button on, and
it never rejects:

```js
const { extension, host, downloadUrl } = await signer.status();
if (!extension || !host) {
  // downloadUrl is where to send them: the published download page, or the
  // link the extension itself supplied for a missing host.
  showLink(`Install DocSigner to sign with your token`, downloadUrl);
}
```

Point it somewhere else with `new DocSigner({ downloadUrl: "https://intranet/…" })`
for an internal mirror. The same URL rides on `EXTENSION_NOT_INSTALLED` and
`HOST_NOT_INSTALLED` as `error.downloadUrl`, so a page that only catches errors
gets it too.

## Documentation

|                                                 |                                                                                                                                                                     |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The API and every error code, frozen            | [CONTRACTS.md](https://github.com/resilient-tech/docsigner/blob/HEAD/CONTRACTS.md)                                                                                  |
| Why a page needs four hops to reach a USB token | [docs/architecture.md](https://github.com/resilient-tech/docsigner/blob/HEAD/docs/architecture.md#the-browser-hop-chain)                                            |
| A full worked example                           | [demo/demo.js](https://github.com/resilient-tech/docsigner/blob/HEAD/demo/demo.js) — [run it](https://github.com/resilient-tech/docsigner/blob/HEAD/demo/README.md) |
| The rest of DocSigner                           | [the repository](https://github.com/resilient-tech/docsigner)                                                                                                       |

Apache-2.0.

---

## Working on it

From a clone of the repo:

```bash
cd js && node --test
```

Releases are built and published from the repo —
[docs/releasing.md](https://github.com/resilient-tech/docsigner/blob/HEAD/docs/releasing.md).
