# DocSigner extension

The WebExtension (Manifest V3) that bridges a web page to the native host. A
content script exposes the page-side API, the background service worker relays
messages to `docsigner-host` over native messaging, and the host reads the
token. Works in Chrome, Edge, Brave, and Firefox.

Files: `manifest.json`, `background.js` (native messaging relay), `content.js`
(page bridge), `consent.html` / `consent.js` (per-site permission prompt),
`icons/` (generated from `../assets/icon.svg` by `../scripts/make_assets.py`).

The consent prompt also carries the update notice. Nobody can push a new version
to a hand-installed native host, and this popup is the one moment the extension
has someone's attention, so it asks the host for `checkUpdate` and shows a line
with a download link when a newer one exists. It never gates the decision: the
buttons work before the check returns, and a slow, failed or absent check shows
nothing at all.

This extension does nothing on its own. The native host must be installed and
registered with this extension's ID (see [`../host/README.md`](../host/README.md)).
When it is not there, `background.js` answers `HOST_NOT_INSTALLED` with a
`downloadUrl` (`HOST_DOWNLOAD_URL`, the published download page) so the page can
offer the install. The extension opens no tab of its own: the page asked for the
signature, so the page decides what the user sees next.

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
