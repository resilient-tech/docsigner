#!/usr/bin/env python3
"""Assert every colour pair in the site's tokens clears its WCAG threshold.

Run it after touching src/styles/tokens.css:

    python3 site/scripts/check_contrast.py          # report + assert
    python3 site/scripts/check_contrast.py --list   # every pair, passing ones too

Contrast is the one accessibility property you can compute, so it gets a check
instead of a promise. Everything else on the list (focus order, heading depth,
colour-as-only-signal) needs eyes.

Thresholds are WCAG 2.2:
  4.5  body text
  3.0  large text (>=24px, or >=19px bold) and non-text UI that carries meaning
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOKENS = Path(__file__).resolve().parents[1] / "src" / "styles" / "tokens.css"


# ---- colour maths -----------------------------------------------------------


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    a, b = luminance(fg), luminance(bg)
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


def over(fg: tuple[int, int, int, float], bg: tuple[int, int, int]) -> tuple[int, int, int]:
    """Flatten a translucent colour onto an opaque one."""
    r, g, b, alpha = fg
    return tuple(round(c * alpha + d * (1 - alpha)) for c, d in zip((r, g, b), bg))


# ---- token parsing ----------------------------------------------------------


def parse(css: str) -> dict[str, dict[str, tuple]]:
    """{'dark': {token: rgb}, 'light': {...}}. Light inherits dark, then overrides."""
    blocks: dict[str, str] = {}
    for match in re.finditer(r"(:root(?:\[data-theme='light'\])?)\s*\{(.*?)\n\}", css, re.S):
        blocks.setdefault(match.group(1), "")
        blocks[match.group(1)] += match.group(2)

    def colours(body: str, inherited: dict | None = None) -> dict[str, tuple]:
        out: dict[str, tuple] = dict(inherited or {})
        mixes: list[tuple[str, str, float]] = []
        for name, raw in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body):
            raw = raw.split("/*")[0].strip()
            if hexed := re.fullmatch(r"#([0-9a-fA-F]{6})", raw):
                h = hexed.group(1)
                out[name] = tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
            elif rgba := re.fullmatch(
                r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)", raw
            ):
                r, g, b, a = rgba.groups()
                vals = (int(float(r)), int(float(g)), int(float(b)))
                out[name] = vals if a is None else (*vals, float(a))
            elif mix := re.fullmatch(
                r"color-mix\(\s*in\s+srgb\s*,\s*var\((--[\w-]+)\)\s+([\d.]+)%\s*,"
                r"\s*transparent\s*\)",
                raw,
            ):
                # Resolved after the pass, since the base may be defined later.
                mixes.append((name, mix.group(1), float(mix.group(2)) / 100))
        for name, base, alpha in mixes:
            if base in out:
                out[name] = (*out[base][:3], alpha)
        return out

    dark = colours(blocks.get(":root", ""))
    # Light inherits dark first, so a mix defined only in :root resolves against
    # whatever the light block overrode its base to.
    light = colours(blocks.get(":root[data-theme='light']", ""), inherited=dark)
    for name, value in dark.items():
        if len(value) == 4 and name in light:
            base = name.rsplit("-", 1)[0]
            if base in light:
                light[name] = (*light[base][:3], value[3])
    return {"dark": dark, "light": light}


# ---- what has to hold -------------------------------------------------------

GROUNDS = ("--bg", "--bg-deep", "--surface", "--well")

# (foreground, threshold, note). Checked against every ground it can sit on.
# Derived from the file, so this works unchanged on any tokens.css and a
# renamed token shows up as missing instead of quietly going unchecked.
#
# Not checked, deliberately: --border and --hover are decoration with no
# contrast floor, and the bare accents (--green, --amber) are fills. A fill's
# job is checked through the label sitting on it, below.
TEXT_TOKENS = {
    "--text": "body",
    "--dim": "secondary text",
    "--faint": "captions and micro-labels",
}
UI_TOKENS = {"--border-strong": "control boundary"}

# Text on a filled accent, rather than on a ground.
ON_FILL = [("--on-accent", "--green", 4.5, "label on the primary fill")]


def inks(tokens: dict) -> list[str]:
    """--green-ink yes, a bare --ink no: that would be some other colour."""
    return sorted(t for t in tokens if t.endswith("-ink") and len(t) > len("--ink"))


def expected(tokens: dict) -> tuple[list, list]:
    """Every -ink token has to carry text, so it is found rather than listed."""
    text = [(t, 4.5, note) for t, note in TEXT_TOKENS.items() if t in tokens]
    text += [(t, 4.5, "accent text") for t in inks(tokens)]
    ui = [(t, 3.0, note) for t, note in UI_TOKENS.items() if t in tokens]
    ui += [(t, 3.0, "accent line") for t in inks(tokens)]
    return text, ui

# Which foregrounds a `-soft` tint is allowed to carry. The tint is a ground in
# its own right: the "Your platform" pill puts --green-ink on --green-soft, and
# that pair sat at 4.27:1 while every plain ground passed.
#
# One rule, so the check matches the design instead of guessing: a tint carries
# its OWN ink, or primary text. Not a foreign ink (amber on a green tint is not a
# pairing this system has), and not --dim or --faint, which are too quiet to sit
# on a coloured panel. Pair something new and this list is where it gets stated.
TINT_CARRIES = ("--text",)


def rows_for(label: str, tokens: dict) -> list:
    """Every (fg, ground) pair worth asserting, for one theme of one file."""
    rows = []
    text, ui = expected(tokens)
    base = {g: tokens[g] for g in GROUNDS if g in tokens}

    def add(fg: str, ground: str, surface: tuple, threshold: float, note: str):
        colour = tokens[fg]
        flat = over(colour, surface) if len(colour) == 4 else colour
        rows.append((label, fg, ground, ratio(flat, surface), threshold, note))

    for fg, threshold, note in text + ui:
        for ground, surface in base.items():
            add(fg, ground, surface, threshold, note)

    # Tints, against their own ink and against primary text.
    for tint, value in tokens.items():
        if not (tint.endswith("-soft") and len(value) == 4):
            continue
        own_ink = f"{tint.removesuffix('-soft')}-ink"
        for fg in (own_ink, *TINT_CARRIES):
            if fg not in tokens:
                continue
            for gname, ground in base.items():
                add(fg, f"{tint} on {gname}", over(value, ground), 4.5, "on its tint")

    for fg, fill, threshold, note in ON_FILL:
        if fg in tokens and fill in tokens:
            rows.append(
                (label, fg, fill, ratio(tokens[fg], tokens[fill]), threshold, note)
            )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="print passing pairs too")
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="tokens.css files to check (default: the site's)",
    )
    args = ap.parse_args()

    rows: list = []
    for path in args.paths or [TOKENS]:
        themes = parse(path.read_text(encoding="utf-8"))
        # site/src/styles/tokens.css -> "site"; desktop/frontend/src/... -> "frontend"
        name = path.parents[2].name
        for theme, tokens in themes.items():
            rows += rows_for(f"{name}/{theme}", tokens)

    failures = []
    for label, fg, bg, got, want, note in rows:
        ok = got >= want
        if not ok:
            failures.append(f"{label}: {fg} on {bg} is {got:.2f}:1, needs {want} ({note})")
        if args.list or not ok:
            print(f"{'ok  ' if ok else 'FAIL'} {label:18} {fg:14} on {bg:14} "
                  f"{got:5.2f}:1  (>= {want})")

    print(f"\n{len(rows)} pairs checked, {len(failures)} failing")
    for line in failures:
        print(f"  {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
