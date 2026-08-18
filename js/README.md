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
