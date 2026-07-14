# opensigner.js

The page-side library. One file, no dependencies. It talks to the browser
extension, which talks to the native host, so a web page can list token
certificates and sign hashes. The API and error codes are in
[`../CONTRACTS.md`](../CONTRACTS.md); `../demo/demo.js` is the full worked
example.

Two builds of the same code:

- `opensigner.js` is an ES module. Import it in a bundler or with
  `<script type="module">`.
- `opensigner.iife.js` is generated from it for a plain `<script>` tag; it
  attaches `window.OpenSigner` and `window.OpenSignerError`.

## Use it

Script tag:

```html
<script src="opensigner.iife.js"></script>
<script>
  const signer = new OpenSigner();
  await signer.init();
  const certs = await signer.listCertificates();
  const { signatures } = await signer.signHash({
    thumbprint: certs[0].thumbprint,
    hashes: [toSignHash],
    digestAlgorithm: "sha256",
  });
</script>
```

ES module:

```js
import { OpenSigner } from "./opensigner.js";
```

Signing needs the extension and the native host installed (see the root README).

## Build

`opensigner.iife.js` is generated. Edit `opensigner.js`, then regenerate:

```bash
npm run build        # or: node build-iife.js
```

## Distribute

Copy the one file you need into your site. No build step is required on the
consuming side. To publish to npm (package name `opensigner`, MIT):

```bash
npm publish
```

## Tests

```bash
node --test
```
