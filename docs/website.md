# Website plan: design and build

`website-plan.md` (11 Aug 2026) covers strategy: the competitive teardown, the
setup funnel spec, site structure, trust signals, hosting. This page is the layer
under it. What the site looks like, how it's built, where the files go, and the
eight places where that plan and this repo disagree.

Read that one first. This one assumes it.

## Decisions taken

| Question | Answer |
|---|---|
| Scope | All 6 phases, Pyodide demo and client-side validator included |
| Docs | Stay in `docs/*.md` on GitHub. No Starlight, no port. |
| Look | The shipped app's palette: dark-first, mint `#4dcd7d`, action blue `#2ca7ff` |
| Framework | Astro, static output, no React |
| Name | DocSigner (the plan's "AnySigner" was a placeholder) |

---

## 1. Eight corrections to the strategy plan

The plan was compiled from outside this repo, so it proposes work that's already
done and one thing that would break a frozen contract. Each of these makes the
build smaller.

### 1.1 Extension detection needs no extension change

The plan's §2.2 builds `externally_connectable` as the Chromium fast path, with
a content-script handshake as the cross-engine baseline. The baseline is already
what ships. `extension/manifest.json` runs `content.js` on `<all_urls>` at
`document_start`, and CONTRACTS §3 defines a `ping` command that the background
worker answers itself, without touching the host and without triggering the
consent prompt. `docsigner.js` wraps it as `init({ timeout })`, which rejects
with `EXTENSION_NOT_INSTALLED`.

So Stage 1 works today on every engine, with no manifest edit and no extra
store-review scrutiny. Drop `externally_connectable` from the build. It buys one
thing we can get more cheaply (§1.2) and costs a permission diff on an extension
whose review is already going to be slow because of `nativeMessaging`.

### 1.2 In-place detection after install does not come free

§2.3 argues the already-open tab heals itself, citing Chromium's
`Dispatcher::OnLoaded` comment about updating bindings when an
`externally_connectable` extension loads. That's true, and it's specific to
those bindings. Content scripts don't get retro-injected into open tabs.

Since we're on the content-script path, an open `/setup` tab stays blind until
it reloads. The cheap fix is the plan's own mechanism #2: a
`chrome.runtime.onInstalled` handler that calls `chrome.tabs.create({ url })`,
which needs no permission. Roughly 6 lines in `background.js`.

Keep the polling anyway. It costs nothing and it's the only thing that covers
Firefox and Safari, where the hand-back is less reliable. Keep the visible
"reload this page" copy too. It's the honest fallback and it's cheaper than
being clever.

### 1.3 The error taxonomy already exists, and it's frozen

§2.5 proposes an `ERR_*` set. CONTRACTS already freezes three layers of codes:

- REST (§1): `DOCUMENT_INVALID`, `CERT_INVALID`, `SESSION_NOT_FOUND`,
  `SESSION_EXPIRED`, `SIGNATURE_INVALID`, `PROFILE_UNSUPPORTED`, `INTERNAL`
- Native (§2): `USER_CANCELLED`, `PIN_INCORRECT`, `PIN_LOCKED`,
  `TOKEN_NOT_FOUND`, `CERT_NOT_FOUND`, `MODULE_ERROR`, `UNSUPPORTED`, `INTERNAL`
- Bridge (§3): `EXTENSION_NOT_INSTALLED`, `HOST_NOT_INSTALLED`, `ORIGIN_DENIED`

Most of the proposed set is these codes under new names. `ERR_TOKEN_ABSENT` is
`TOKEN_NOT_FOUND`. `ERR_PIN_CANCELLED` is `USER_CANCELLED`. Minting a parallel
vocabulary on the website would give integrators two names for one condition,
which is the version rot the plan warns about in §2.7, one layer up.

The site renders the frozen codes. Two gaps in the plan are real and worth a
CONTRACTS changelog entry, separately from the site:

- A version-skew code carrying `{ component, detected, required }`. Nothing
  covers this today.
- The integrator-is-stale case, where the calling site's `docsigner.js` is old.

`ERR_TOKEN_DRIVER_MISSING` needs no new code. `listCertificates` already returns
`readers` beside `certificates`, so "a reader is present and the certificate
list is empty" is the driver-missing signal, computed page-side. `demo/demo.js`
already does this at line 131.

### 1.4 There's no architecture to choose, so §2.6 mostly evaporates

§2.6 spends its length on UA-CH high-entropy values, Rosetta, Windows-on-ARM,
and correcting a wrong guess after install. Every one of those matters when you
ship more than one build per OS. The release ships exactly one:
`host-macos` (x86_64), `host-windows` (x64), `host-linux` (x64). The release
notes say so: "One download per operating system. Pick yours; there is no
architecture to choose."

macOS being x86_64 is deliberate, not a gap. Roadmap D8 has the reasoning: the
desktop `.app` stays x86_64 so the sidecar can load x86_64-only token drivers.

So: no `getHighEntropyValues`, no bitness, no `Accept-CH` or `Critical-CH`
headers, no post-install architecture correction. OS family off the UA string is
all `/download` and `/setup` need, and for OS family the UA string is reliable.

Two things survive from §2.6, both cheap: "Not your platform? Show all
downloads," and the universal2 recommendation, which belongs on the roadmap
rather than the website.

### 1.5 `latest.json` is already the single source of truth

§2.7 asks for a served `versions.json` so version numbers can't rot across
surfaces. `.github/workflows/release.yml` already builds and publishes
`latest.json` on every release, at
`releases/latest/download/latest.json`, holding `version`, `url`, `published`,
and a `downloads` map keyed `host-macos`, `host-windows`, `host-linux`,
`desktop-macos`, `desktop-windows`, `desktop-linux`, `extension-chrome`,
`extension-firefox`. It's built from the artifacts that actually exist, so a job
that didn't run is absent instead of a dead link.

`SHA256SUMS` ships beside it, one file covering everything.

So `/download` reads those two at build time and no new CI work is needed for
versions or hashes. File sizes come from the releases API, which reports `size`
per asset. What's genuinely missing for the plan's trust block is attestations
and code signing, and both are already open roadmap items (D7).

Don't invent a second feed. The host already consumes this one via `checkUpdate`
(CONTRACTS §2), so a divergent site feed would be the exact failure §2.7 is
about.

### 1.6 The version handshake is built

§2.4 says to design in-band version reporting now. `getVersion` and
`checkUpdate` are both in CONTRACTS §2, implemented, tested, and reachable as of
the 2026-08-11 changelog entry. `docsigner.js` exposes `checkUpdate()`, and it
never rejects on a network or feed problem: those arrive as
`updateAvailable: false` with a message.

The consent prompt already runs its own `checkUpdate` and shows a line naming
the newer version with a link, and the host drops any `downloadUrl` that isn't
`https://`. `/setup` reads the same call. Nothing to design.

### 1.7 Nothing to link to yet, and the repo is private

`origin` is `resilient-tech/docsigner`, currently private. Roadmap D1 has the
extension unsubmitted to both stores. D6 (the Homebrew tap) and D7 (Windows
signing) both wait on the repo going public.

Two consequences for the build:

1. Every outbound URL lives in one file, `src/config.ts`. Going public, or
   getting a store ID, is one edit.
2. `/setup` Stage 1 needs an honest unpublished path. A "load unpacked"
   instruction and a zip link, not a store button that 404s. The same gap is
   already visible in `demo/demo.js:6`, where `INSTALL_EXTENSION_URL` and
   `INSTALL_HOST_URL` are both `"#"`.

The domain recommendation in §6 stands and it's the one item I'd act on before
writing copy, because store listing URLs are the expensive ones to change later.
Until it's bought, `src/config.ts` holds the placeholder and no hostname gets
printed into package metadata.

### 1.8 The demo runs a different pyHanko than the product

§4 verified pyHanko in Pyodide at `pyhanko==0.35.0`, pinned there because 0.36.2
wants `cryptography>=48` and Pyodide ships 47. `core/pyproject.toml` asks for
`pyhanko[image-support]>=0.35`, an open lower bound, so a fresh install resolves
to 0.36.2.

The demo's pitch is "your actual library, in your browser, nothing uploaded."
With a version skew that needs an asterisk. Pick one before writing the page:

- Say the version on the page, plainly. Cheapest, and honest.
- Pin `core` to what Pyodide can run. Ties the product to the demo's ceiling.
  Not worth it.
- Wait for Pyodide to ship `cryptography>=48`. Blocks phase 4 on somebody else.

First option. Print the version next to the result and move on.

Worth writing down now: the demo is the only part of this site whose
dependencies are somebody else's release schedule. Every Pyodide release can
change what's installable. Treat a broken demo as expected maintenance, and keep
it on a page that can be pulled without touching the rest of the site.

---

## 2. Design system

Dark by default, because the app is. `data-theme="light"` on `<html>` swaps the
colour map and nothing else, same mechanism the desktop app and the demo page
already use.

### 2.1 Where the tokens come from

`site/src/styles/tokens.css` starts as a copy of
`desktop/frontend/src/tokens.css`, with a header comment naming the source.

A copy, not an import. Cloudflare Pages builds with `site/` as the root
directory, so reaching up into `desktop/` would work locally and break in CI.
The two files will drift, and that's fine: marketing needs a display type tier
the app has no use for, and the app needs component tokens the site never
touches. The shared part is the colour map, which changes about once a year.

Skipped: a CI check that the colour blocks match. Add one if drift ever causes a
visible problem.

### 2.2 Colour

Four hues total: a grey ramp, mint, action blue, and red. Red appears only on an
invalid signature or a failed check, so when it shows up it means something.

| Token | Dark | Light | Used for |
|---|---|---|---|
| `--bg` | `#131314` | `#f5f6f8` | page |
| `--bg-deep` | `#0b0b0c` | `#eef0f3` | alternating sections |
| `--surface` | `#212123` | `#ffffff` | cards |
| `--raised` | `#282828` | `#ffffff` | menus, popovers |
| `--well` | `#08090a` | `#edeff2` | code blocks, insets |
| `--hover` | `#3c3c3c` | `#eceef2` | hover fill |
| `--border` | `#303132` | `#e2e5ea` | hairlines |
| `--border-strong` | `#48484a` | `#ccd2db` | inputs, dashed drops |
| `--text` | `#e6e6e6` | `#1d2433` | body |
| `--dim` | `#a0a0a0` | `#5b6472` | secondary |
| `--faint` | `#7c7c7c` | `#98a1b0` | captions, labels |
| `--green` | `#4dcd7d` | same | brand, valid, primary CTA |
| `--action` | `#2ca7ff` | same | links, focus ring |
| `--amber` | `#e0a04b` | same | update available, warning |
| `--red` | `#e5484d` | same | invalid, error |

The accents hold across both themes. They read on either ground, which is why
the app gets away with one set.

The logo keeps its own mint gradient (`#4dcd7d` to `#37a862`) inside the mark.
It's the only gradient on the site.

### 2.3 Type

The app's stack, plus a self-hosted fallback so the site doesn't change face
between a Mac and a Windows laptop:

```css
--font: 'Avenir Next', 'Avenir', 'Nunito Sans', system-ui, -apple-system,
        'Segoe UI', Roboto, Arial, sans-serif;
--mono: ui-monospace, 'SF Mono', SFMono-Regular, Menlo, monospace;
```

Avenir Next renders natively on macOS. Everyone else gets Nunito Sans, self
hosted as two woff2 files (400 and 600, latin subset, about 35 KB together),
`font-display: swap`, with the 400 preloaded. Mono is the system stack, zero
bytes, and code looks native.

The app tops out at 28px. A marketing page needs more, and it needs a bigger
body than the app's 14px:

| Token | Size | Used for |
|---|---|---|
| `--display-1` | `clamp(2.25rem, 5vw, 3.25rem)` | hero headline, 600 |
| `--display-2` | `clamp(1.75rem, 3.5vw, 2.25rem)` | section headline, 600 |
| `--display-3` | `1.375rem` | card and subsection titles, 600 |
| `--text-lede` | `1.125rem` | hero subhead, 400 |
| `--text-body` | `1rem` | body, 400 |
| `--text-sm` | `0.875rem` | captions, table cells |
| `--text-xs` | `0.75rem` | uppercase labels, 0.08em tracked |

Headlines get `letter-spacing: -0.01em` and `line-height: 1.15`. Body runs
`1.6`. Prose columns cap at `68ch`.

### 2.4 Spacing, radius, motion

4px base, inherited: `4 8 12 16 24 32 48 64 96 128`. Section padding is
`96px` desktop, `64px` mobile. Radii come from the app (`4px` chips, `6px`
inputs, `10px` cards, `100px` pills) with one addition, `--radius-lg: 16px`, for
the hero and feature cards, because a marketing card at 10px reads cramped at
that size.

Motion stays the app's: `--dur: 0.2s`, `--dur-fast: 0.05s`, `--ease:
cubic-bezier(0.33, 0, 0, 1)`. Everything respects
`prefers-reduced-motion: reduce`.

No scroll-triggered animation, no parallax, no counters that tick up. Hover and
focus states, and the theme transition. That's the budget.

### 2.5 Icons

Lucide, via `astro-icon` and `@iconify-json/lucide`. Inlined as SVG at build
time, so no runtime and no icon font. The logo mark is Lucide's `signature`
already, and `NOTICE` already carries the ISC attribution.

Stroke width 1.75 to match the app's `base.css`. Icons are `1em` and inherit
`currentColor`. Decorative ones get `aria-hidden`.

### 2.6 Accessibility, not negotiable

Contrast is the one property here you can compute, so it has a check rather than
a promise: `site/scripts/check_contrast.py`, which runs over any `tokens.css`.

```bash
python3 site/scripts/check_contrast.py \
    site/src/styles/tokens.css desktop/frontend/src/tokens.css
```

It found 26 failing pairs on the first run, and the values in §2.2 are what came
out of fixing them. Two lessons worth keeping:

- **A hue picked for a dark UI does not carry text on a light one.** The colour
  map was measured off the dark app and reused unchanged, so `--faint` sat at
  2.26:1 in light and mint managed 1.9:1. Hence the `-ink` pair: `color:` takes
  `-ink`, `background:` takes the base hue. And it isn't only a light-theme
  problem, `--red` failed in dark too.
- **A tint is a ground.** The "your platform" pill puts `--green-ink` on
  `--green-soft`, and that pair was 4.27:1 while every flat ground passed.

The rest needs eyes, and these are the rules:

- Focus ring is `2px solid var(--action-ink)` at `2px` offset, never removed, and
  it sets no `border-radius`. Setting one reshapes the focused element; a 6px
  button snapped to 4px on tab.
- Colour never carries meaning alone. The platform-matched download card says
  "Your platform" in words next to the green edge.
- `/setup` state changes announce via `aria-live="polite"`. The three rows are a
  `<ul>` with real text in each state, so a screen reader gets the state without
  the colour.
- Theme toggle is a real `<button>` whose accessible name says what the click
  does. No `aria-pressed`: with a changing name it reads as "switch to dark
  theme, toggle button, not pressed".
- `prefers-reduced-motion` and `prefers-contrast: more` both answered.
- Skip link to `<main>`.

### 2.7 The other surfaces

The colour map is shared, so a token defect is never only the website's. Fixed at
the same time, and worth knowing about before touching either:

- **The desktop app** used `--faint` as a text colour in 13 rules and had 20
  accent-as-text declarations. Its `tokens.css` is the origin of the map, so the
  fix went there first and the site copied it forward. The demo page links that
  stylesheet directly, so it came along.
- **The app's PIN field** had `outline: none` with a 1px border change as its
  only focus indicator. Of every control in the product that one has the least
  business hiding focus.
- **The extension's consent dialog** was the only surface off the design system
  altogether: five hardcoded hex values and `color-scheme: light` pinned, so it
  flashed white over a dark browser. It now has both themes, stated explicitly in
  each branch. It stays self-contained on purpose, with the tokens copied rather
  than imported, because it has to render correctly even when nothing else
  loads.

---

## 3. Structure

Astro, static output, no React. The repo's own line is "Python backend, plain JS
everywhere else" and that holds here: Astro components for structure, plain
`<script type="module">` for the four pages that need behaviour.
`demo/demo.js` already proves the pattern works for exactly this kind of UI.

```
site/
├── astro.config.mjs
├── package.json
├── pnpm-workspace.yaml              # allowBuilds; pnpm 10+ needs it (§4.1)
├── public/
│   ├── _headers                     # CSP, MIME, cache (§4.2)
│   ├── theme.js                     # sets the theme before paint (§4.2)
│   ├── .well-known/security.txt
│   ├── favicon.svg                  # from assets/icon.svg
│   ├── fonts/                       # nunito-sans-{400,600}.woff2 + OFL text
│   └── og.png
└── src/
    ├── config.ts                    # every outbound URL, one place (§1.7)
    ├── styles/
    │   ├── tokens.css               # from desktop/frontend/src/tokens.css
    │   ├── base.css                 # reset, type, focus, skip link
    │   └── prose.css
    ├── lib/
    │   ├── release.ts               # latest.json + SHA256SUMS, build time
    │   ├── platform.ts              # OS family off the UA (§1.4)
    │   └── messages.js              # shared error copy (§3.2)
    ├── components/                  10 files, all of them live
    │   ├── Layout.astro             head, SiteNav, SiteFooter
    │   ├── SiteNav.astro            checkbox mobile menu, no JS
    │   ├── SiteFooter.astro         one row
    │   ├── ThemeToggle.astro
    │   ├── Button.astro             primary | default | ghost, sm | md | lg
    │   ├── Section.astro            alternating ground, max-width, padding
    │   ├── Callout.astro            note | warning | limit
    │   ├── Hero.astro
    │   ├── FlowStrip.astro          page → extension → helper → token
    │   └── DownloadCard.astro       version, size, SHA-256, verify line
    ├── pages/
    │   ├── index.astro
    │   ├── setup.astro
    │   ├── download.astro
    │   ├── how-it-works.astro
    │   ├── standards.astro
    │   ├── components.astro
    │   ├── security.astro
    │   ├── compare.astro
    │   ├── demo.astro
    │   ├── verify.astro
    │   └── 404.astro
    └── scripts/
        ├── theme.js
        ├── setup.js                 the state machine (§2 of the strategy plan)
        ├── demo.worker.js           Pyodide, off the main thread
        └── verify.worker.js
```

### 3.1 Rules that keep it maintainable

- A component earns its file when it's used twice, or when it holds behaviour.
  No wrappers around a single `<div>`. The cut in §5 orphaned `Card`, `Tabs` and
  `CodeBlock`; all three were deleted rather than kept for a phase that might
  want them. Git has them.
- Styles live in the component's own `<style>` block. Astro scopes them. Only
  tokens, reset, and prose are global.
- No page holds a hardcoded URL, version, or hash. Those come from `config.ts`
  and `lib/release.ts`.
- Client JS only on `/setup`, `/demo`, `/verify`, and the theme toggle. Every
  other page ships zero. Phase 1 totals 1.6 KB across three files.
- Anything CSS can do, CSS does. The mobile menu is a checkbox and the theme
  swap is one attribute on `<html>`.
- Set `vite.build.assetsInlineLimit: 0`. Astro inlines small component scripts
  into the HTML, the CSP blocks inline scripts, and the dev server doesn't send
  `_headers`, so the breakage only appears once deployed.

### 3.2 Share the error copy, don't rewrite it

`demo/demo.js:10` already holds a plain sentence for every frozen error code,
written in the product's voice. `/setup` needs the same table.

Move it to `js/messages.js`, a sibling of `docsigner.js`, and have both the demo
and the site import it. `docsigner.js` stays untouched, because CONTRACTS §4
says "Nothing else in the API" and this isn't API, it's copy. One line in
`js/README.md` names the new file.

That also fixes `demo/demo.js:6`, where the two install URLs are `"#"`. They
become the site's real ones.

---

## 4. Build and deploy

### 4.1 Monorepo placement

`site/` at the repo root, beside `demo/` and `js/`. Self-contained: its own
`package.json`, its own lockfile, no workspace wiring. `desktop/frontend` is
already a standalone pnpm project with no root workspace, so this matches what's
there.

Cloudflare Pages, root directory `site/`, build `pnpm build`, output `dist`.
`pnpm` pinned in `packageManager`, same idea as the desktop frontend, because the
release workflow already hit "No pnpm version is specified" once.

pnpm 10 and newer refuse to run a dependency's install scripts until they're
named, and `pnpm install` fails outright rather than warning. The setting is
`allowBuilds` in `pnpm-workspace.yaml`; it is not `pnpm.onlyBuiltDependencies` in
`package.json` and not `.npmrc`, both of which are silently ignored. esbuild and
sharp need it.

One `README.md` in `site/` for the commands, per the docs convention: door,
concept, commands.

### 4.2 `public/_headers`

Two things from §6 of the strategy plan that are real:

```
/dl/*
  Content-Type: application/octet-stream
  Content-Disposition: attachment
  Cache-Control: public, max-age=31536000, immutable
```

Pages sends no `Content-Type` for `.msi`, so Chrome renders the installer as
text. We're pointing binaries at GitHub Releases anyway (better trust story,
and the 25 MiB per-asset cap rules them out), so `/dl/*` only matters if that
ever changes. Ship the header now; it costs a line.

Skipped: the `Accept-CH` and `Critical-CH` headers. Those exist to make
high-entropy client hints available on the first request, and §1.4 removed the
need for them.

The CSP is a real header in the same file, not a `<meta>` tag. Meta delivery
silently ignores `frame-ancestors`, and a header can differ per path, which is
what `/demo` will need for Pyodide's `wasm-unsafe-eval`. The site has no
third-party scripts, no analytics and no CDN fonts, so the policy gets to be
tight: `script-src 'self'` with no `'unsafe-inline'`.

That last part has a trap in it, and it cost an hour. `script-src 'self'` blocks
your own inline `<script>`, including the theme-init script that has to run
before the first paint. The theme silently stops working and nothing in the build
says so. Two ways out:

- Astro's `experimental.csp` hashes inline scripts into the policy. It's the
  purpose-built answer and on Astro 5.18.2 it emitted no policy at all on a
  static build, with `csp: true` or a full config. Not used.
- Serve the theme init as `public/theme.js` and load it blocking in `<head>`.
  `'self'` covers it, there's no hash to keep in step with the source, and
  nothing paints before `<head>` is parsed so there's no flash. About 300 bytes
  from the same origin.

Second one. A file also can't rot out of sync with a hash, which an inline script
plus a build-time hash would.

`style-src` does allow `'unsafe-inline'`, because Astro emits component styles as
inline `<style>` blocks. A style block can't execute.

### 4.3 What the build fetches

`lib/release.ts` fetches `latest.json`, `SHA256SUMS`, and the releases API at
build time, not in the browser. Three consequences worth stating: the download
page is static HTML, a rate limit or an outage can't break a visitor's page
load, and a new release needs a rebuild to show up. Cloudflare Pages has a
deploy hook, so the release workflow can call it as its last step.

While the repo is private, those fetches 404. `lib/release.ts` falls back to the
version in `host/Cargo.toml` and renders the download cards without hashes,
with an honest line saying the release isn't public yet.

---

## 5. Copy

`resilient-brand/02-voice/anti-ai-writing-style.md` governs every word. The
banned list is a hard rule. No em dashes. Sentence case headers. Contractions.

**Cut first, then cut again.** The first build of the home page had 7 sections:
hero, architecture strip, three tabbed flows with code samples, a standards
table, a quickstart, a 6-card feature grid, and a closing call to action. It
built fine and read like every other developer marketing site. The page was
4,763 pixels tall.

What shipped is 4 blocks and 1,899 pixels: hero, the architecture strip, two
short paragraphs on who holds the key, one call to action. The footer went from
4 columns and 20 links to a single row. Nothing that mattered was lost, because
almost none of it mattered on the first screen.

The standards depth, the code samples and the profile table are all real
differentiators. They belong on the pages someone reaches once they care, not on
the one they land on. A visitor deciding whether this tool is for them needs the
category, the one rule, and a download link.

So: a section earns its place by answering a question the visitor is already
asking. Everything else moves to a page they choose to open.

Beyond that, three rules specific to this site:

**Say the number.** "A 200 MB file signs as fast as a 200 KB one" beats any
adjective. "32-byte hash out, 256-byte signature back." "The host is about 1 MB
of Rust." The README already writes this way; match it.

**Never promise what isn't shipped.** The extension isn't in either store. The
repo is private. Windows builds aren't signed. Two of the release artifacts have
never been opened. A signing product that oversells its install story has picked
the worst possible thing to lie about. Where something's missing, the page says
so and says when.

**No hero slogan.** The first line names the category, the way the README does:
"Open-source digital signatures for PDFs. Sign with a USB token from any
website, or with a key on your own server." Somebody who signs invoices for a
living should know in one line whether this is for them.

The three-tone rule applies to language too. Say it once, in the shortest words
that are still true, then stop.

---

## 6. Build order

Phases follow the strategy plan's §7, adjusted for what §1 removed.

| Phase | Ship | Notes |
|---|---|---|
| 0 | Domain | §1.7. Do it before any store submission or package metadata. |
| 1 | **Done.** `site/` scaffold, design system, `Layout`, nav, footer, theme toggle, `/`, `/how-it-works`, `/download`, `security.txt`, 404 | Still open from this phase: `SECURITY.md` at the repo root, and the `og.png`. |
| 2 | `/setup` | Three rows, poll plus `focus` and `visibilitychange`, diagnostics with a copy button, the frozen error codes. Plus `js/messages.js` (§3.2) and the 6-line `onInstalled` hand-back (§1.2). |
| 3 | `/verify` | Client-side PAdES validation. No off-the-shelf equivalent exists, so this is real engineering, not a page. Weeks. |
| 4 | `/demo` | Pyodide. Print the pyHanko version (§1.8). Worker, lazy-loaded behind a click, real byte counter. |
| 5 | `/standards`, `/compare`, `/components`, `/security` | Mostly writing. `/standards` is the sharpest differentiator per the plan's §3 and the material is already in `docs/architecture.md`. |
| 6 | Blog, Hindi, integrator docs for linking to `/setup` | |

Phases 1, 2, and 5 are days each. Phases 3 and 4 are the ones that can slip, and
neither blocks anything else. If either stalls, the site still stands without it.

Two things to land in phase 1 regardless, both from the plan and both still
right: publish the error-code list so integrators can branch on it, and wire
release attestations into CI so `/download` has something true to show.
