# DocSigner extension

The WebExtension (Manifest V3) that bridges a web page to the native host. A
content script exposes the page-side API, the background service worker relays
messages to `docsigner-host` over native messaging, and the host reads the
token. Works in Chrome, Edge, Brave, and Firefox.

Files: `manifest.json`, `background.js` (native messaging relay), `content.js`
(page bridge), `consent.html` / `consent.js` (per-site permission prompt),
`icons/` (generated from `../assets/icon.svg` by `../scripts/make_assets.py`).

This extension does nothing on its own. The native host must be installed and
registered with this extension's ID (see [`../host-rs/README.md`](../host-rs/README.md)).

Why the hops are shaped this way, and what each one is allowed to do:
[`../docs/architecture.md`](../docs/architecture.md#the-browser-hop-chain).

## Load it (development)

Chrome / Edge / Brave: open `chrome://extensions`, turn on Developer mode, click
Load unpacked, and pick this `extension/` folder. Copy the extension ID it
assigns; the host installer needs it.

Firefox: Chrome refuses a manifest that declares an event-page background, and
Firefox needs one, so generate the Firefox copy first:

```bash
python scripts/build_firefox_extension.py     # -> dist/firefox-extension/
```

Then open `about:debugging` → This Firefox → Load Temporary Add-on, and pick
`dist/firefox-extension/manifest.json`. Firefox also asks you to grant site
access per site in the extension's settings.

## Pack it (for the stores)

Chrome Web Store takes a zip of the unpacked folder:

```bash
cd extension && zip -r ../dist/docsigner-extension.zip . -x '*.DS_Store'
```

Firefox (AMO) takes a zip of the generated Firefox build:

```bash
python scripts/build_firefox_extension.py
cd dist/firefox-extension && zip -r ../docsigner-firefox.zip .
```

Store review and signing are done in each store's dashboard. Bump `version` in
`manifest.json` before packing a new upload.
