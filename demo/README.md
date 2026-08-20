# Running the demo page

A working integration example: pick a PDF, pick a certificate, sign it. Useful
for trying the extension, and for copying into your own page.

## 1. Serve the repo root

```bash
python3 -m http.server 8080
```

From the repo root, not from `demo/` — the page imports `js/docsigner.js` from
its sibling folder, and browsers block `file://` fetches.

## 2. Open it

```
http://localhost:8080/demo/
```

The trailing `/demo/` matters; the root is just a file listing.

That is enough to see the whole UI and the extension's consent prompt. Signing
needs one of the two sections below.

## 3a. Sign with a token

Needs the extension and the native host:

- **Extension** — `chrome://extensions` → Developer mode → Load unpacked →
  pick `extension/`. Copy the ID it assigns.
  ([`../extension/README.md`](../extension/README.md))
- **Host** — install it and register it with that ID.
  ([`../host/README.md`](../host/README.md))

Then click **List certificates**. The first time, a small popup asks whether
this site may see your certificates.

## 3b. Sign with a server-held key

No token, no extension. In a second terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ./core -e ./server
cp .env.example .env             # Windows: copy .env.example .env
python -m docsigner_server       # http://127.0.0.1:8001
```

Run it from the repo root — `.env` is read from wherever you launch. Then pick
**Server-held key** under *Sign with*.

## If it says the extension is not installed

Reload the page. A newly loaded unpacked extension does not inject into tabs
that were already open.

Still failing? Check the card on `chrome://extensions` points at `extension/`
and not `dist/firefox-extension/`, which is Firefox-only.

## Seeing the consent prompt again

It is remembered per site, so it appears once. To see it without clearing
anything, open the page directly — the site name comes from the URL:

```
chrome-extension://<YOUR_EXTENSION_ID>/consent.html?origin=https://example.com
```

To actually reset it: `chrome://extensions` → DocSigner → **service worker** →
Console:

```js
chrome.storage.local.remove("origins")
```
