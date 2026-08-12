#!/usr/bin/env python3
"""Build design/styleguide.html.

Inlines tokens.css, base.css and the repo's own fonts so the page always shows exactly
what the token file says, and so it opens from disk with no server and no
network. Re-run after editing tokens.css.
"""

import base64
import pathlib

HERE = pathlib.Path(__file__).parent


# The repo's own font files, read where they already live. No copy in design/:
# one more copy is how the two tokens.css files drifted in the first place.
FONT_SRC = {
    "nunito-sans-400.woff2": "../site/public/fonts/nunito-sans-400.woff2",
    "nunito-sans-600.woff2": "../site/public/fonts/nunito-sans-600.woff2",
    "PlusJakartaSans-SemiBold.woff2": (
        "../desktop/frontend/src/fonts/PlusJakartaSans-SemiBold.woff2"
    ),
}


def font(name):
    path = HERE / FONT_SRC[name]
    if not path.exists():  # running outside the repo, e.g. from a copy
        path = HERE / "fonts" / name
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:font/woff2;base64,{data}"


def svg(body, cls="lucide"):
    return (
        f'<svg class="{cls}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="1.75" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


ICONS = {
    "SETTINGS": svg(
        '<path d="M21 4H14"/><path d="M10 4H3"/><path d="M21 12H12"/>'
        '<path d="M8 12H3"/><path d="M21 20H16"/><path d="M12 20H3"/>'
        '<circle cx="12" cy="4" r="2"/><circle cx="10" cy="12" r="2"/>'
        '<circle cx="14" cy="20" r="2"/>'
    ),
    "INFO": svg('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>'),
    "WARN": svg(
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
        '<path d="M12 9v4"/><path d="M12 17h.01"/>'
    ),
    "FAIL": svg('<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>'),
    "GLOBE": svg(
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
        "lucide md",
    ),
    "PUZZLE": svg(
        '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/>'
        '<path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
        "lucide md",
    ),
    "TERM": svg('<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>', "lucide md"),
    "KEY": svg(
        '<path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4"/>'
        '<path d="m21 2-9.6 9.6"/><circle cx="7.5" cy="15.5" r="5.5"/>',
        "lucide md",
    ),
    "CHEV": svg('<path d="m9 18 6-6-6-6"/>'),
    "LOCK": svg(
        '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
        "lucide md",
    ),
    # The mark from assets/icon.svg: Lucide 'signature'.
    "LOGO": svg(
        '<path d="m21 17-2.156-1.868A.5.5 0 0 0 18 15.5v.5a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1'
        "c0-2.545-3.991-3.97-8.5-4a1 1 0 0 0 0 5c4.153 0 4.745-11.295 5.708-13.5"
        'a2.5 2.5 0 1 1 3.31 3.284"/><path d="M3 21h18"/>'
    ),
}

CSS = "\n".join(
    (HERE / f).read_text() for f in ("tokens.css", "base.css", "styleguide-extra.css")
)

FONT_FACES = f"""
@font-face {{ font-family:'Nunito Sans'; font-style:normal; font-weight:400;
  font-display:swap; src:url({font('nunito-sans-400.woff2')}) format('woff2'); }}
@font-face {{ font-family:'Nunito Sans'; font-style:normal; font-weight:600;
  font-display:swap; src:url({font('nunito-sans-600.woff2')}) format('woff2'); }}
@font-face {{ font-family:'Plus Jakarta Sans'; font-style:normal; font-weight:600;
  font-display:swap; src:url({font('PlusJakartaSans-SemiBold.woff2')}) format('woff2'); }}
"""

JS = r"""
const root = document.documentElement;

document.querySelectorAll('[data-set-theme]').forEach(b => {
  b.addEventListener('click', () => {
    const t = b.dataset.setTheme;
    if (t === 'paper') root.setAttribute('data-theme', 'paper');
    else root.removeAttribute('data-theme');
    document.querySelectorAll('[data-set-theme]').forEach(o =>
      o.setAttribute('aria-pressed', String(o === b)));
    paint();
  });
});

const val = n => getComputedStyle(root).getPropertyValue(n).trim();

function rgb(c) {
  const p = document.createElement('span');
  p.style.color = c; document.body.appendChild(p);
  const m = getComputedStyle(p).color.match(/[\d.]+/g).slice(0, 3).map(Number);
  p.remove(); return m;
}
function lum(c) {
  const [r, g, b] = rgb(c).map(v => {
    v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (a, b) => {
  const x = lum(a), y = lum(b), hi = Math.max(x, y), lo = Math.min(x, y);
  return (hi + 0.05) / (lo + 0.05);
};

const GROUND = ['--well', '--bg-deep', '--bg', '--surface', '--raised'];
const TEXTS = [
  ['--text', 'The document never leaves your server.'],
  ['--dim', 'Supporting prose and secondary labels.'],
  ['--faint', 'Micro-labels, timestamps, placeholders.'],
  ['--green-ink', 'Signature valid · chain complete'],
  ['--action-ink', 'Read how it works'],
  ['--amber-ink', 'Signed, not yet LTV'],
  ['--red-ink', 'Signature did not verify'],
];
const HUES = [
  ['green', 'Brand · valid', 'DocSigner, and a signature that verified.'],
  ['action', 'Action', 'Links, focus, selection, in progress.'],
  ['amber', 'Amber', 'Signed but not yet LTV. Driver missing.'],
  ['red', 'Red', 'A check that did not pass. Nothing else.'],
];
const SPACE = [1, 2, 3, 4, 5, 6, 8, 12, 16, 24, 32];
const RADII = ['--radius-card', '--radius-sm', '--radius', '--radius-lg', '--pill'];
const ICONS = ['--icon-xs', '--icon-sm', '--icon-md', '--icon-lg'];

function paint() {
  // ground swatches
  document.querySelector('[data-swatches]').innerHTML = GROUND.map(g =>
    `<div class="sw"><div class="sw-chip" style="background:var(${g})"></div>
     <div class="sw-meta"><code>${g}</code><span>${val(g)}</span></div></div>`).join('');

  // text rows, live contrast against the worst ground in this theme
  const worst = root.hasAttribute('data-theme') ? '--well' : '--raised';
  document.querySelector('[data-text-rows]').innerHTML = TEXTS.map(([t, s]) => {
    const r = ratio(val(t), val(worst));
    return `<div class="row" style="background:var(${worst})">
      <code>${t}</code>
      <span class="sample" style="color:var(${t})">${s}</span>
      <span class="ratio ${r >= 4.5 ? 'pass' : 'fail'}">${r.toFixed(2)}:1</span></div>`;
  }).join('');

  // hues
  document.querySelector('[data-hues]').innerHTML = HUES.map(([k, name, note]) =>
    `<div class="hue">
       <div class="hue-fill" style="background:var(--${k})">--${k} fill · --on-accent</div>
       <div class="hue-body">
         <b style="color:var(--${k}-ink)">--${k}-ink · ${name}</b>
         <span>${note}</span>
         <div class="hue-soft" style="background:var(--${k}-soft);color:var(--${k}-ink)">--${k}-soft</div>
       </div>
     </div>`).join('');

  // space
  document.querySelector('[data-space]').innerHTML = SPACE.map(n =>
    `<div><i style="width:var(--s-${n})"></i>--s-${n}</div>`).join('');

  // radii
  document.querySelector('[data-radii]').innerHTML = RADII.map(r =>
    `<div style="border-radius:var(${r})">${r.replace('--radius-', '').replace('--radius', 'radius').replace('--', '')}</div>`).join('');

  // icons
  document.querySelector('[data-icons]').innerHTML = ICONS.map(s =>
    `<figure><svg class="lucide" style="width:var(${s});height:var(${s})"
       xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
       stroke="currentColor" stroke-width="1.75" stroke-linecap="round"
       stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2"/>
       <path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
     <figcaption>${s.replace('--icon-', '')} ${val(s)}</figcaption></figure>`).join('');
}
paint();
"""

BODY = (HERE / "styleguide-body.html").read_text()
for key, markup in ICONS.items():
    BODY = BODY.replace(f"__ICON_{key}__", markup)
BODY = BODY.replace("__LOGO__", ICONS["LOGO"])

HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DocSigner design system</title>
<meta name="description" content="Tokens, type, and component recipes for DocSigner. Ledger and Paper.">
<style>
{FONT_FACES}
{CSS}
</style>
</head>
<body>
{BODY}
<script>{JS}</script>
</body>
</html>
"""

out = HERE / "styleguide.html"
out.write_text(HTML)
print(f"{out}  {out.stat().st_size / 1024:.0f} KB")
