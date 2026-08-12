#!/usr/bin/env python3
"""Build design/prototypes/hero.html.

Inlines design/tokens.css, design/base.css, hero.css and the repo's own fonts,
so the prototype opens from disk with no server and no network and always
reflects the current tokens. Re-run after editing any of them.
"""

import base64
import pathlib

HERE = pathlib.Path(__file__).parent
DESIGN = HERE if (HERE / "tokens.css").exists() else HERE.parent

FONT_SRC = {
    "nunito-sans-400.woff2": "../site/public/fonts/nunito-sans-400.woff2",
    "nunito-sans-600.woff2": "../site/public/fonts/nunito-sans-600.woff2",
    "PlusJakartaSans-SemiBold.woff2": (
        "../desktop/frontend/src/fonts/PlusJakartaSans-SemiBold.woff2"
    ),
}


def font(name):
    path = DESIGN / FONT_SRC[name]
    if not path.exists():
        path = DESIGN / "fonts" / name
    return f"data:font/woff2;base64,{base64.b64encode(path.read_bytes()).decode()}"


def svg(body, cls="lucide", extra=""):
    return (
        f'<svg class="{cls}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="1.75" '
        f'stroke-linecap="round" stroke-linejoin="round" {extra}>{body}</svg>'
    )


# The mark from assets/icon.svg: Lucide 'signature'. pathLength="1" lets one
# dash rule draw both strokes at the same rate regardless of their real length.
SIG_PATHS = (
    '<path pathLength="1" d="m21 17-2.156-1.868A.5.5 0 0 0 18 15.5v.5a1 1 0 0 1-1 1h-2'
    'a1 1 0 0 1-1-1c0-2.545-3.991-3.97-8.5-4a1 1 0 0 0 0 5c4.153 0 4.745-11.295 '
    '5.708-13.5a2.5 2.5 0 1 1 3.31 3.284"/><path pathLength="1" d="M3 21h18"/>'
)

ICONS = {
    "LOGO": svg(SIG_PATHS),
    "LOGO_DRAW": svg(SIG_PATHS, cls="lucide draw"),
    "LOCK": svg(
        '<rect width="18" height="11" x="3" y="11" rx="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "SUN": svg(
        '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/>'
        '<path d="m4.9 4.9 1.4 1.4"/><path d="m17.7 17.7 1.4 1.4"/><path d="M2 12h2"/>'
        '<path d="M20 12h2"/><path d="m6.3 17.7-1.4 1.4"/><path d="m19.1 4.9-1.4 1.4"/>'
    ),
    "FOLDER": svg(
        '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6a2 2 0 '
        '0 1-1.94 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 '
        '0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>'
    ),
    "REFRESH": svg(
        '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>'
        '<path d="M21 3v5h-5"/>'
        '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>'
        '<path d="M8 16H3v5"/>'
    ),
    "FILE": svg(
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/>'
        '<path d="M16 17H8"/>',
        "lucide qrow-ic",
    ),
    "OK": svg(
        '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>', "lucide s-ok"
    ),
    "SKIP": svg('<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/>', "lucide s-skip"),
    "PREV": svg('<path d="m15 18-6-6 6-6"/>'),
    "NEXT": svg('<path d="m9 18 6-6-6-6"/>'),
    "SERVER": svg(
        '<rect width="20" height="8" x="2" y="2" rx="2"/>'
        '<rect width="20" height="8" x="2" y="14" rx="2"/>'
        '<path d="M6 6h.01"/><path d="M6 18h.01"/>'
    ),
    "USB": svg(
        '<circle cx="10" cy="7" r="1"/><circle cx="4" cy="20" r="1"/>'
        '<path d="M4.7 19.3 19 5"/><path d="m21 3-3 1 2 2Z"/>'
        '<path d="M9.26 7.68 5 12l2 5"/><path d="m10 14 5 2 3.5-3.5"/>'
        '<path d="m18 12 1-1 1 1-1 1Z"/>'
    ),
    "PEN": svg(
        '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83'
        'l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497Z"/>'
        '<path d="m15 5 4 4"/>'
    ),
}

# ---- the paper artwork -------------------------------------------------
# Drawn rather than screenshotted so it themes with --paper-* and stays sharp.

INK = "var(--paper-ink)"


def rules(x, y, widths, gap=9, w=1.6, o=0.16):
    return "".join(
        f'<rect x="{x}" y="{y + i * gap}" width="{wd}" height="{w}" rx="0.8" '
        f'fill="{INK}" opacity="{o}"/>'
        for i, wd in enumerate(widths)
    )


SIG_STAMP = f"""
<svg class="stamp" viewBox="0 0 200 54" preserveAspectRatio="xMidYMid meet"
     aria-label="Signature stamp">
  <path d="M6 34c11-3 17-20 23-23s8 11 3 17-11 5-8-2 12-11 22-11 14 8 23 6 12-11 19-11"
        fill="none" stroke="{INK}" stroke-width="1.8" stroke-linecap="round" opacity="0.85"/>
  <rect x="6" y="40" width="120" height="1.2" fill="{INK}" opacity="0.25"/>
  <text x="6" y="49" font-size="7" fill="{INK}" opacity="0.6"
        font-family="system-ui, sans-serif">Digitally signed by Smit Vora</text>
</svg>
"""

# A deterministic block pattern that reads as a QR without pretending to be one.
_QR = [
    "1111111010101111111", "1000001011001000001", "1011101000101011101",
    "1011101011101011101", "1011101001001011101", "1000001010101000001",
    "1111111010101111111", "0000000011000000000", "1101011101011010110",
    "0010110001100101001", "1101001011010110110", "0100110100101001001",
    "1111111001101101011", "0000001010010110010", "1011101101011011101",
    "1011101001100100110", "1011101110010111011", "1000001011001001001",
    "1111111001101110110",
]


def qr(x, y, size):
    cell = size / len(_QR)
    out = [f'<rect x="{x}" y="{y}" width="{size}" height="{size}" fill="#fff"/>']
    for r, row in enumerate(_QR):
        for c, v in enumerate(row):
            if v == "1":
                out.append(
                    f'<rect x="{x + c * cell:.2f}" y="{y + r * cell:.2f}" '
                    f'width="{cell:.2f}" height="{cell:.2f}" fill="{INK}"/>'
                )
    return "".join(out)


PAGE_DOC = f"""
<svg class="doc-page" viewBox="0 0 300 388" aria-label="Document page">
  {rules(28, 34, [150], gap=0, w=4, o=0.55)}
  {rules(28, 52, [244, 244, 210], gap=9)}
  {rules(28, 96, [244, 232, 244, 188], gap=9)}
  {rules(28, 146, [96], gap=0, w=3, o=0.4)}
  {rules(28, 160, [244, 244, 226, 244, 170], gap=9)}
  {rules(28, 218, [244, 210, 244, 150], gap=9)}
  {rules(28, 266, [180, 244, 122], gap=9)}
</svg>
"""

PAGE_INVOICE = f"""
<svg class="doc-page" viewBox="0 0 460 650" aria-label="Tax invoice print format">
  <text x="34" y="52" font-size="15" font-weight="600" fill="{INK}"
        font-family="system-ui, sans-serif">Resilient Software Services LLP</text>
  <text x="34" y="70" font-size="8.5" fill="{INK}" opacity="0.55"
        font-family="system-ui, sans-serif">GSTIN 24AAOFR1234M1Z5 · Ahmedabad, Gujarat</text>
  <text x="426" y="52" font-size="10" font-weight="600" fill="{INK}" text-anchor="end"
        font-family="system-ui, sans-serif" letter-spacing="1.6">TAX INVOICE</text>
  <text x="426" y="70" font-size="8.5" fill="{INK}" opacity="0.55" text-anchor="end"
        font-family="system-ui, sans-serif">ACC-SINV-2026-0412 · 12 Aug 2026</text>
  <rect x="34" y="86" width="392" height="1.4" fill="{INK}" opacity="0.35"/>

  {rules(34, 104, [70], gap=0, w=2.4, o=0.35)}
  {rules(34, 116, [180, 150], gap=9)}
  {rules(280, 104, [70], gap=0, w=2.4, o=0.35)}
  {rules(280, 116, [146, 120], gap=9)}

  <rect x="34" y="158" width="392" height="1.2" fill="{INK}" opacity="0.25"/>
  {rules(34, 168, [64], gap=0, w=2.2, o=0.3)}
  {rules(300, 168, [40], gap=0, w=2.2, o=0.3)}
  {rules(386, 168, [40], gap=0, w=2.2, o=0.3)}
  <rect x="34" y="180" width="392" height="1.2" fill="{INK}" opacity="0.25"/>

  {rules(34, 194, [210], gap=0, w=2, o=0.16)}
  {rules(300, 194, [34], gap=0, w=2, o=0.16)}
  {rules(392, 194, [34], gap=0, w=2, o=0.16)}
  {rules(34, 218, [178], gap=0, w=2, o=0.16)}
  {rules(300, 218, [34], gap=0, w=2, o=0.16)}
  {rules(392, 218, [34], gap=0, w=2, o=0.16)}
  {rules(34, 242, [232], gap=0, w=2, o=0.16)}
  {rules(300, 242, [34], gap=0, w=2, o=0.16)}
  {rules(392, 242, [34], gap=0, w=2, o=0.16)}
  <rect x="34" y="266" width="392" height="1.2" fill="{INK}" opacity="0.25"/>

  {rules(300, 286, [50], gap=0, w=2.2, o=0.3)}
  {rules(386, 286, [40], gap=0, w=2.6, o=0.5)}
  {rules(300, 304, [50], gap=0, w=2.2, o=0.3)}
  {rules(392, 304, [34], gap=0, w=2.6, o=0.5)}

  <!-- what DocSigner actually puts on the page -->
  <g transform="translate(34 470)">
    <rect x="0" y="0" width="200" height="86" rx="3" fill="none"
          stroke="{INK}" stroke-width="1" opacity="0.3"/>
    <path d="M14 42c11-3 17-20 23-23s8 11 3 17-11 5-8-2 12-11 22-11 14 8 23 6 12-11 19-11"
          fill="none" stroke="{INK}" stroke-width="1.9" stroke-linecap="round" opacity="0.85"/>
    <rect x="14" y="52" width="128" height="1.1" fill="{INK}" opacity="0.25"/>
    <text x="14" y="64" font-size="7.5" fill="{INK}" opacity="0.72"
          font-family="system-ui, sans-serif">Digitally signed by SMIT VORA</text>
    <text x="14" y="75" font-size="6.8" fill="{INK}" opacity="0.5"
          font-family="system-ui, sans-serif">Date: 2026.08.12 11:04:31 +05'30'</text>
    {qr(152, 8, 40)}
  </g>
  <text x="34" y="580" font-size="6.8" fill="{INK}" opacity="0.45"
        font-family="ui-monospace, monospace">CCA-LTA · SHA-256 · verify at erp.yourcompany.in/verify/9f2b…c41e</text>
</svg>
"""

HERO_ART = f"""
<svg class="hero-sheet" viewBox="0 0 340 250" aria-hidden="true">
  {rules(0, 6, [126], gap=0, w=3.4, o=0.5)}
  {rules(0, 24, [300, 300, 268], gap=11)}
  {rules(0, 72, [300, 286, 300, 232], gap=11)}
  {rules(0, 130, [188, 300, 146], gap=11)}
  <g transform="translate(0 176)">
    <rect x="0" y="0" width="214" height="66" rx="3" fill="none"
          stroke="{INK}" stroke-width="1" opacity="0.22"/>
    <path class="ink" pathLength="1"
          d="M16 34c12-3 18-21 25-24s9 12 3 18-12 5-9-2 13-12 24-12 15 9 25 7 13-12 21-12"
          fill="none" stroke="{INK}" stroke-width="2.1" stroke-linecap="round"
          stroke-linejoin="round" opacity="0.88"/>
    <rect x="16" y="44" width="140" height="1.1" fill="{INK}" opacity="0.22"/>
    <text x="16" y="56" font-size="8" fill="{INK}" opacity="0.7"
          font-family="system-ui, sans-serif">Digitally signed by SMIT VORA</text>
    {qr(166, 6, 40)}
  </g>
</svg>
"""

# ---- assembly ----------------------------------------------------------

CSS = "\n".join(
    (DESIGN / f).read_text() for f in ("tokens.css", "base.css")
) + "\n" + (HERE / "hero.css").read_text()

DRAW_CSS = """
/* One beat, then still: the mark draws itself once, on load. */
.brand-mark .draw path {
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  animation: mark-draw 900ms var(--ease) 250ms forwards;
}
.brand-mark .draw path:last-child { animation-delay: 900ms; animation-duration: 400ms; }
@keyframes mark-draw { to { stroke-dashoffset: 0; } }

.hero-sheet { display: block; width: 100%; height: auto; }
.hero-sheet .ink {
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  animation: mark-draw 1500ms var(--ease) 500ms forwards;
}

@media (prefers-reduced-motion: reduce) {
  .brand-mark .draw path { animation: none; stroke-dashoffset: 0; }
  .hero-sheet .ink { animation: none; stroke-dashoffset: 0; }
  [data-wire].run .pip { animation: none !important; opacity: 0; }
}
"""

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
const $ = (s, c = document) => c.querySelector(s);
const $$ = (s, c = document) => [...c.querySelectorAll(s)];

/* colour scheme */
$$('[data-set-theme]').forEach(b => b.addEventListener('click', () => {
  b.dataset.setTheme === 'paper'
    ? root.setAttribute('data-theme', 'paper')
    : root.removeAttribute('data-theme');
  $$('[data-set-theme]').forEach(o => o.setAttribute('aria-pressed', String(o === b)));
}));

/* which product surface. The wire is not decoration: each surface really does
   move a different number of bytes, and the desktop app moves none. */
const SURFACES = {
  web: { left: 'Your server', bytes: '288', unit: 'bytes' },
  app: { left: 'Your disk',   bytes: '0',   unit: 'bytes',
         note: 'Nothing crosses the network at all. The desktop app signs from ' +
               'disk, with no server and no extension — the token is on the same ' +
               'machine as the files.' },
  erp: { left: 'Your ERPNext server', bytes: '288', unit: 'bytes' },
};
let surface = 'web';

$$('[data-surface]').filter(e => e.tagName === 'BUTTON').forEach(b =>
  b.addEventListener('click', () => {
    surface = b.dataset.surface;
    $$('.tabs [data-surface]').forEach(o => {
      o.classList.toggle('active', o === b);
      o.setAttribute('aria-selected', String(o === b));
    });
    $$('figure.surface').forEach(f => { f.hidden = f.dataset.surface !== surface; });
    render();
  }));

/* the only number that changes */
const FILES = [
  { name: 'statement_march.pdf',    n: '240',  u: 'KB', kb: '240 KB',       ratio: '853' },
  { name: 'invoice_2026_0412.pdf',  n: '12.4', u: 'MB', kb: '12,698 KB',    ratio: '45,147' },
  { name: 'annual_report_2025.pdf', n: '1.8',  u: 'GB', kb: '1,887,437 KB', ratio: '6,710,192' },
];
let file = 1;

function render() {
  const f = FILES[file];
  const s = SURFACES[surface];

  $$('[data-doc-name]').forEach(e => e.textContent = f.name);
  $$('[data-doc-size-kb]').forEach(e => e.textContent = f.kb);
  $('[data-doc-size]').textContent = f.n;
  $('[data-doc-unit]').textContent = f.u;

  $('[data-wire-bytes]').textContent = s.bytes;
  $('[data-node-left]').textContent = s.left;
  $('.wire').classList.toggle('quiet', s.bytes === '0');

  $('[data-note]').innerHTML = s.note
    ? s.note
    : `288 bytes moved. <strong>${f.n} ${f.u}</strong> did not. That is a ratio of ` +
      `1 : ${f.ratio} — and it is why a ${f.n} ${f.u} file signs as fast as a 240 KB one.`;

  $$('[data-file]').forEach(b => b.classList.toggle('active', +b.dataset.file === file));
  run();
}
$$('[data-file]').forEach(b => b.addEventListener('click', () => { file = +b.dataset.file; render(); }));

/* one beat, then still */
let t;
function run() {
  const w = $('[data-wire]');
  w.classList.remove('run');
  void w.offsetWidth;          // restart the animation, do not queue a second
  w.classList.add('run');
  clearTimeout(t);
  t = setTimeout(() => w.classList.remove('run'), 2400);
}
render();
"""

BODY = (HERE / "hero-body.html").read_text()
for key, markup in ICONS.items():
    BODY = BODY.replace(f"__ICON_{key}__", markup)
BODY = BODY.replace("__LOGO_DRAW__", ICONS["LOGO_DRAW"])
BODY = BODY.replace("__LOGO__", ICONS["LOGO"])
BODY = BODY.replace("__HERO_ART__", HERO_ART)
BODY = BODY.replace("__PAGE_DOC__", PAGE_DOC)
BODY = BODY.replace("__PAGE_INVOICE__", PAGE_INVOICE)
BODY = BODY.replace("__SIG_STAMP__", SIG_STAMP)

HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DocSigner — hero prototype</title>
<meta name="description" content="The document never leaves your server. 288 bytes cross the network, whatever the file size.">
<style>
{FONT_FACES}
{CSS}
{DRAW_CSS}
</style>
</head>
<body>
{BODY}
<script>{JS}</script>
</body>
</html>
"""

out = HERE / "hero.html"
out.write_text(HTML)
print(f"{out}  {out.stat().st_size / 1024:.0f} KB")
