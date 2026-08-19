# DocSigner extension

The WebExtension (Manifest V3) that bridges a web page to the native host. A
content script exposes the page-side API, the background service worker relays
messages to `docsigner-host` over native messaging, and the host reads the
token. Chrome, Edge, Brave, and Firefox.

| File                          | What it does                                                       |
| ----------------------------- | ------------------------------------------------------------------ |
| `manifest.json`               | permissions, and the version the stores key updates off            |
| `background.js`               | native messaging relay                                             |
| `content.js`                  | page bridge                                                        |
| `consent.html` / `consent.js` | per-site permission prompt                                         |
| `icons/`                      | generated from `../assets/icon.svg` by `../scripts/make_assets.py` |

**It does nothing on its own.** The native host must be installed and registered
with this extension's ID — see [`../host/README.md`](../host/README.md). Without
it, `background.js` answers `HOST_NOT_INSTALLED` with a `downloadUrl` so the page
can offer the install. The extension opens no tab of its own: the page asked for
the signature, so the page decides what the user sees next.

The consent prompt doubles as the update notice. Nobody can push a new version to
a hand-installed host, and this popup is the one moment we have someone's
attention, so it asks the host for `checkUpdate` and shows a download line when a
newer one exists. It never gates the decision — the buttons work before the check
returns, and a slow or failed check shows nothing.

Why the hops are shaped this way:
[`../docs/architecture.md`](../docs/architecture.md#the-browser-hop-chain).

## Load it (development)

**Chrome / Edge / Brave** — `chrome://extensions` → Developer mode → Load
unpacked → pick this `extension/` folder. Copy the extension ID it assigns; the
host installer needs it.

**Firefox** — Chrome refuses a manifest that declares an event-page background
and Firefox needs one, so build the Firefox copy first:

```bash
python scripts/build_firefox_extension.py     # -> dist/firefox-extension/
```

Then `about:debugging` → This Firefox → Load Temporary Add-on → pick
`dist/firefox-extension/manifest.json`. Firefox also asks you to grant site
access per site.

## Ship it (to the stores)

**Don't zip it by hand, and don't edit `version`.** Every release builds both
zips and attaches them, with the version already bumped:

```bash
docsigner-extension-<version>-chrome.zip     → Chrome Web Store
docsigner-extension-<version>-firefox.zip    → Firefox Add-ons
```

Download them from the release page and upload each to its dashboard, where
review and signing happen. The version in `manifest.json` moves on its own,
whenever `extension/` changed — [`../docs/releasing.md`](../docs/releasing.md).
