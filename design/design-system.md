# DocSigner design system

This is the system that was already here, with a second colour scheme added
and the gaps closed. [`tokens.css`](tokens.css) is the values,
[`base.css`](base.css) the element defaults, [`fonts.css`](fonts.css) the
faces. When this file and the CSS disagree, the CSS wins and this file is
wrong.

**Nothing was renamed.** Every token the tree already references still exists,
with the same name and — with one exception noted below — the same value. A
file picks this up by pointing at `design/` instead of its local copy.

## What changed

| | |
|---|---|
| **Added** | PAPER, a warm second colour scheme, replacing the cool blue-grey light map |
| **Added** | `--amber-ink`, `--red-ink` — the `-ink` pattern existed for mint and blue and stopped short |
| **Added** | `--paper` / `--paper-ink` / `--paper-line`, `--green-hover`, `--hairline`, `--focus-ring`, icon sizes, z-index scale, control heights, breakpoints, `--lh-dense`, `--tracking-brand`, `--measure-lede`, `--measure-h1` |
| **Changed** | `--faint` `#7c7c7c` → `#8e8e8e`. One value, explained below |
| **Changed** | light-theme mint `#1f7a45` → `#16713d`, blue `#0b6bbf` → `#0b63b8`. Both were just under AA on the warm ground |
| **Moved** | `@font-face` out of `tokens.css` and `base.css` into `fonts.css` |
| **Unchanged** | the dark map, the type stack, the wordmark, the radii, the spacing, the shadows, the motion, every token name |

The type stack and the wordmark are the parts of this system that were already
right, and they are untouched: Avenir Next where it is native, Nunito Sans
self-hosted everywhere else, system mono, and Plus Jakarta SemiBold for
`.brand` and nothing else.

## Two colour schemes

| | Dark (default) | Paper |
|---|---|---|
| Ground | ink, unchanged | warm stock |
| Depth from | hairlines and a little blur | hairlines, almost no blur |
| Reads as | the machine's view — the tool | the document's view — the artifact |

The old light map was `#f5f6f8` on `#1d2433` — a blue-grey screen colour.
Every open-source signing product ships that plus a blue accent; DocuSeal and
Documenso both do. Stock and ink is the one this product can own, and it is
the same idea as the dark theme rather than its inverse: a signature is a
document act.

Dark stays the default. `data-theme="light"` is kept as an alias for
`"paper"`, so `theme.js`, `localStorage` and anything bookmarked keep working
— rename at leisure.

## The `-ink` rule

This was already in the system; it just stopped at two hues.

- **plain** (`--green`, `--red`) is a **fill**. It carries `--on-accent` text
  on both themes.
- **`-ink`** (`--green-ink`, `--red-ink`) is **text, borders and icons**.

Mint at 9.3:1 on `#131314` drops to 1.7:1 on stock, which is why the pair
exists. Extending it to amber and red closes two holes: amber text had no
paper form, and `--red` was doing both jobs at 3.77:1 on `--raised`.

Red is the one hue whose **fill** is identical on both themes. Darkening it for
paper would put `--on-accent` at 2.9:1 on its own button — the gate caught
that.

## Contrast

Verified, not eyeballed. Worst case per token across `--bg`, `--bg-deep`,
`--well`, `--surface`, `--raised`:

| | Dark | Paper |
|---|---|---|
| `--text` | 11.81 | 13.99 |
| `--dim` | 5.64 | 5.74 |
| `--faint` | 4.50 | 4.72 |
| `--green-ink` | 7.26 | 4.79 |
| `--action-ink` | 5.67 | 4.75 |
| `--amber-ink` | 6.53 | 5.00 |
| `--red-ink` | 5.08 | 5.18 |

`--on-accent` on fills: green 9.47, action 7.40, amber 8.51, red 4.91.

```bash
python3 design/check-contrast.py     # exits non-zero on a failure
```

Two notes on what the gate found:

**`--faint` moved.** At `#7c7c7c` it was 3.53:1 on `--raised`, and the things
it labels — the 11px uppercase field labels, the 10.5px file subtitle — are
small text, where AA asks 4.5. `#8e8e8e` is the smallest value that clears it
on every ground. This is the one visible change to the dark theme, and it is
the one place the old map was failing a check the product itself would not
have shipped. Revert with a single line if you disagree.

**`--border-strong` is reported, not enforced.** It sits at 1.62:1 on
`--raised`. WCAG 1.4.11 asks 3:1 of a boundary only when the boundary is the
sole way to identify a control, and here controls are identified by their
`--surface` fill against `--bg`; `--border-strong` draws dividers and the skip
link. If you ever build a control whose only edge is this token — a
transparent-fill input, a borderless segmented switch — move it to the
enforced list in the script and raise it to at least `#717171`.

## The paper swatch

`--paper`, `--paper-ink`, `--paper-line` are **theme-independent**, and
unrelated to the PAPER scheme. A rendered PDF page and a signature preview are
pictures of paper, and paper does not have a dark mode. `app.css` was
hardcoding `#fff` and `#d6dae1` for exactly this. Use `.paper` from
`base.css`.

In the dark theme this makes the document the one bright object on the screen,
which is the picture worth making: the artifact, lit, on the workbench.

## Density

Sizes are in `rem`, so the root font size is the knob and there is one ladder:

```
site         html { font-size: 100%  }   16px base
desktop app  html { font-size: 87.5% }   14px base
extension    html { font-size: 87.5% }
```

That is what retires `13.5px`, `12.5px`, `11.5px` and `10.5px` from `app.css`.
Each of those was reaching for a density change and now gets one. Spacing
stays in px on the 4px grid: it is physical distance, not reading size.

## What the additions fix

Each of these was a real inconsistency in the tree, not a hypothetical:

- **`--hairline`** — the system is drawn with hairlines, so it is a token now,
  not a habit repeated in forty places.
- **`--focus-ring`** — `base.css` used offset 1px, `SiteNav` used 2px, the
  extension had none. One ring, and the ground-coloured inner band keeps it
  visible on a mint-filled button.
- **`--icon-xs/sm/md/lg`** (14/16/20/24, stroke 1.75) — the tree had 17, 18,
  20, 24, 34 and `1.05em` in play.
- **`--control-h-sm/md/lg`** (32/38/46) and `--control-sq` — the 34px theme
  toggle sat next to a 38px button in `SiteNav`. The square button is now
  `--sm`, so they line up.
- **`--z-*`** — `SiteNav` had a bare `20`, the modal a bare `1000`.
- **`--bp-sm/md/lg`** (640/768/1024) — the tree had 760, 768 and 860 doing one
  job. `@media` cannot read a custom property, so these must still be typed as
  literals; the tokens are the one place the numbers are written down.
- **`--green-hover`** — `Button.astro` had a raw `#3fbf6f`, the only hardcoded
  colour in the site components. The token is the logo gradient's deeper stop,
  so a mint button darkens toward the mark.
- **`--accent-bar`, `--underline-w`, `--nav-h`, `--nav-blur`, `--nav-veil`,
  `--disabled-opacity`** — all were magic numbers in two or more files.

## Component recipes

Not a component library — the rules a component follows so two people build
the same thing. The style guide is the live version of this list.

**Button.** `--control-h-sm/md/lg`, padding `--control-px-*`, radius
`--radius-sm`, `1px solid transparent` border so variants swap border colour
without reflow, transition at `--dur-fast`.

- `primary` — `--green` fill, `--on-accent` text, `--green-hover` on hover.
  One per view. It is the signing action.
- `default` — `--surface` fill, `var(--hairline)`, `--text`.
- `ghost` — transparent, `var(--hairline)`, `--dim` → `--text` on hover.
- `danger` — `--red-ink` text, `--red-soft` on hover. Never a red fill; a red
  fill in this system means a verification failed.

The size words also need to agree: `Button.astro` uses `sm|md|lg` and
`app.css` uses `sm|big` for the same `.btn` class, and `demo/index.html` uses
both. Pick `sm|md|lg`.

**Card.** `--surface`, `var(--hairline)`, `--radius`, `--s-6`, no shadow in
either theme. A thing that needs a shadow is a menu or a modal. Selected:
`border-color: var(--green)` — one edge, not a border plus a 1px ring drawing
the same line twice, which is what `DownloadCard` does today.

**Callout / banner / status line.** `var(--hairline)` with
`border-left-width: var(--accent-bar)` in the tone's `-ink`, background
`--surface` for note or the tone's `-soft` otherwise. Tones: note (action),
warn (amber), fail (red). `Callout.astro`, the app's `.banner` and the demo's
`#status` are three implementations of this one component.

**Control.** `--surface` fill, `var(--hairline)`, `--radius-sm`, height
`--control-h-sm`, `--faint` placeholder. Focus takes `--focus-ring`, not a
border-colour change — `.pin-field` currently does the latter.

**Chip.** `--pill`, `var(--hairline)`, `--dim`, `--text-xs` semibold. Active:
`--action-ink` text, `--action` border, `--action-soft` background.

**Micro-label.** `.label` from `base.css`. The same block is written three
times today — `DownloadCard dt`, demo `.card-head`, demo `.server-row` — with
two different weights.

**Nav.** `--nav-h`, sticky at `--z-nav`, background
`color-mix(in srgb, var(--bg) var(--nav-veil), transparent)` with
`backdrop-filter: blur(var(--nav-blur))`. Active item:
`inset 0 calc(-1 * var(--underline-w)) 0 var(--green)`.

**Modal.** `--bg`, `var(--hairline)`, `--radius-lg`, `--shadow-lift`, overlay
at `--z-overlay`.

**Paper swatch.** `.paper`. Both themes.

## Do / don't

- **Do** write `-ink` for text and the plain token for fills.
- **Do** run `check-contrast.py` after touching a colour.
- **Do** let the density knob handle "this feels too big in the app".
- **Don't** use `--red` for anything except a check that did not pass — not a
  close button, not a required-field asterisk, not "remove from queue". Those
  are `--faint` until hovered.
- **Don't** write `--font-brand` anywhere except `.brand`. Wanting it
  elsewhere means shipping another cut of Jakarta.
- **Don't** add a fifth hue. Four is the budget, and it is why the fourth one
  lands.
- **Don't** add a shadow to a card, or invent a fourth breakpoint.

## Adopting it

No renames, so this can go file by file and stop anywhere.

1. **Point at it.** Replace `site/src/styles/tokens.css` and `base.css` with
   one-line `@import` of `design/tokens.css` and `design/base.css`, or delete
   them and fix the import in `Layout.astro`. Add `fonts.css` with the site's
   font paths. Same for `desktop/frontend/src/tokens.css`, whose hand-copy is
   the reason `--font-brand` and the display tier were only in one place.
2. **Look at it in Paper.** The scheme is the visible change; everything else
   is a no-op. If a component looks wrong, it is almost always using a fill
   token where it wanted `-ink`.
3. **Density.** Add `html { font-size: 87.5% }` to the app, then replace the
   fractional px sizes in `app.css` with the `--text-*` ladder.
4. **Collect the wins.** The focus ring, `.label`, `.sr-only`, `.paper`,
   `--green-hover` and the icon sizes each delete a local copy of themselves.
5. **The two loose files.**
   - `demo/index.html` — already token-consuming for colour, but hardcodes
     every size in a 170-line inline `<style>`. Move it onto the scale.
   - `extension/consent.html` — zero tokens and its own blue (`#1a56db`),
     which is a fifth accent nobody approved. It pins `color-scheme: light`
     deliberately to dodge a black-on-black bug, so give it the PAPER map
     only: `data-theme="paper"` on `<html>`, load `tokens.css`, inherit. It
     does not need a webfont.
