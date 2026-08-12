# site

The website. Astro, static output, no framework and no client-side router.

The design and the reasoning behind it are in [`docs/website.md`](../docs/website.md).
This file is the commands.

## Run it

Needs Node 20 or newer and pnpm.

```bash
cd site
pnpm install
pnpm dev          # http://localhost:4321
```

```bash
pnpm build        # -> dist/
pnpm preview      # serves dist/
pnpm check        # types and unused props
```

After touching `src/styles/tokens.css`, re-run the contrast check. It takes both
token files, since the colour map is shared with the desktop app:

```bash
python3 scripts/check_contrast.py \
    src/styles/tokens.css ../desktop/frontend/src/tokens.css
```

`pnpm install` needs `pnpm-workspace.yaml`'s `allowBuilds` block. pnpm 10 and
newer refuse to run a dependency's install scripts until they're named there.

## Deploy

Cloudflare Pages.

| Setting | Value |
|---|---|
| Root directory | `site` |
| Build command | `pnpm build` |
| Output directory | `dist` |

Nothing else. No environment variables, no adapter.

`src/lib/release.ts` fetches `latest.json`, `SHA256SUMS` and the releases API
**at build time**, so `/download` is static HTML and a GitHub outage can't break
a visitor's page load. The cost: a new release only appears after a rebuild. Add
a Pages deploy hook and call it from the last step of `.github/workflows/release.yml`.

While the repo is private those fetches 404, and the page falls back to the
version in `host/Cargo.toml` with an honest "not released yet" notice.

## Layout

```
public/          served as-is: _headers, theme.js, fonts, favicon, security.txt
src/config.ts    every outbound URL and which pages exist
src/styles/      tokens.css (the theme), base.css
src/lib/         release.ts (build-time), platform.ts (browser)
src/components/  Astro components, styles scoped to each
src/pages/       one file per route
```

Two conventions worth knowing before you edit:

**No page hardcodes a URL or a version.** They come from `src/config.ts` and
`src/lib/release.ts`. `config.ts` also has a `pages` map saying which routes
exist, so nav and footer never link to something unbuilt. Landing a new page is
one flag flip.

**Client JavaScript is the exception, not the default.** Every page ships zero
except the theme toggle and the copy buttons. Tabs are radio inputs and CSS. The
mobile menu is a checkbox. Adding a `<script>` should feel like a decision.

## Colour

Two rules, and the check enforces the second one:

**`color:` takes an `-ink` token, `background:` takes the base.** A hue chosen to
sit on `#131314` does not automatically carry text on `#ffffff`: brand mint is
7.9:1 on the dark grounds and 1.9:1 on the light ones. So `--green` is a fill and
`--green-ink` is the text and any line that means something. On dark they mostly
coincide, which is why the split is easy to forget.

**A tint counts as a ground.** `--green-soft` under `--green-ink` was 4.27:1 while
every flat ground passed.

## Theme

Dark by default. `data-theme="light"` on `<html>` swaps the colour map in
`tokens.css` and nothing else.

`public/theme.js` sets it before the first paint and is loaded blocking in
`<head>`. It's a file rather than an inline script because the CSP in
`public/_headers` sets `script-src 'self'` with no `'unsafe-inline'`. Inlining it
gets it blocked, silently, and the theme just stops working.
