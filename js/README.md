# docsigner.js

The page-side library. One file, no dependencies. It talks to the browser
extension, which talks to the native host, so a web page can list token
certificates and sign hashes. The API and error codes are in
[`../CONTRACTS.md`](../CONTRACTS.md); `../demo/demo.js` is the full worked
example.

`docsigner.js` is an ES module. Import it in a bundler or straight from a
`<script type="module">` tag; there is nothing to build.

Where this sits in the whole flow, and why the page needs 4 hops to reach a USB
token: [`../docs/architecture.md`](../docs/architecture.md#the-browser-hop-chain).

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

Signing needs the extension and the native host installed (see the root README).

## Distribute

Copy the one file you need into your site. No build step is required on the
consuming side. To publish to npm (package name `docsigner`, MIT):

```bash
npm publish
```

## Tests

```bash
node --test
```
