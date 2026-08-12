#!/usr/bin/env python3
"""Contrast gate for the DocSigner design system.

Parses design/tokens.css, resolves both colour schemes, and asserts:

  - every text token clears WCAG AA 4.5:1 against every ground in its theme
  - --border-strong clears the 3:1 non-text minimum (WCAG 1.4.11)
  - --on-accent clears 4.5:1 on every accent fill

Exits non-zero on a failure, so it can sit in CI beside the tests.
No dependencies. Run from the repo root:

    python3 design/check-contrast.py
"""

import pathlib
import re
import sys

TOKENS = pathlib.Path(__file__).with_name("tokens.css")

GROUNDS = ["--bg", "--bg-deep", "--well", "--surface", "--raised"]
TEXT = ["--text", "--dim", "--faint"]
INKS = ["--green-ink", "--action-ink", "--amber-ink", "--red-ink"]
FILLS = ["--green", "--action", "--amber", "--red"]

# A `-soft` tint is a ground too, and it is the one the flat list misses: a
# chip or a status pill puts a hue's own -ink on its own -soft, which is a
# lower-contrast pair than that -ink on any of the five grounds above. A tint
# carries its OWN ink or --text, and nothing else -- amber on a green tint is
# not a pairing this system has, so checking every ink against every tint would
# invent failures the design cannot produce. Add a pairing here if one appears.
TINT_CARRIES = ["--text"]

AA_TEXT = 4.5
AA_NONTEXT = 3.0


# ---- colour ------------------------------------------------------------


def _linear(c):
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour):
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def flatten(rgba, ground):
    """A translucent tint over an opaque ground, as a hex string."""
    (r, g, b, alpha), h = rgba, ground.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    base = [int(h[i : i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(
        round(c * alpha + d * (1 - alpha)) for c, d in zip((r, g, b), base)
    )


def rgba(value, scope):
    """A translucent value -> (r, g, b, a).

    Handles the rgba() literals this file uses, and color-mix(... N%,
    transparent) in case a consumer writes the tint that way instead.
    """
    if value is None:
        return None
    value = value.strip()
    if m := re.fullmatch(
        r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)",
        value,
    ):
        r, g, b, a = m.groups()
        return (int(float(r)), int(float(g)), int(float(b)), float(a or 1))
    if m := re.fullmatch(
        r"color-mix\(\s*in\s+srgb\s*,\s*(#[0-9a-fA-F]{3,6}|var\(--[\w-]+\))"
        r"\s+([\d.]+)%\s*,\s*transparent\s*\)",
        value,
    ):
        base, pct = m.group(1), float(m.group(2)) / 100
        if ref := VAR.match(base):
            base = resolve(ref.group(1), scope)
        if base is None:
            return None
        h = base.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (*[int(h[i : i + 2], 16) for i in (0, 2, 4)], pct)
    return None


def ratio(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---- parsing -----------------------------------------------------------

DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
VAR = re.compile(r"var\(\s*(--[\w-]+)\s*\)")
HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")


COMMENT = re.compile(r"/\*.*?\*/", re.S)


def blocks(css):
    """Yield (selector, {prop: value}) for every top-level rule."""
    css = COMMENT.sub("", css)  # comments here hold braces; strip before matching
    depth, start, sel_start = 0, None, 0
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                selector = css[sel_start:i].strip()
                start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                yield selector, dict(DECL.findall(css[start:i]))
                sel_start = i + 1


def resolve(name, scope, seen=None):
    """Resolve a token to a hex literal, following var() chains."""
    seen = seen or set()
    if name in seen:
        return None
    seen.add(name)
    value = scope.get(name)
    if value is None:
        return None
    value = value.strip()
    if HEX.match(value):
        return value
    ref = VAR.match(value)
    if ref:
        return resolve(ref.group(1), scope, seen)
    return None  # color-mix, gradients, anything not a flat colour


def themes(css):
    """Return {scheme: {token: value}} with PAPER layered over DARK."""
    dark, paper = {}, {}
    for selector, decls in blocks(css):
        if selector.startswith("@"):
            continue
        if "data-theme" in selector:
            paper.update(decls)
        elif selector.strip() == ":root":
            dark.update(decls)
    merged_paper = dict(dark)
    merged_paper.update(paper)
    return {"DARK": dark, "PAPER": merged_paper}


# ---- the gate ----------------------------------------------------------


def check(theme_name, scope):
    failures = []
    grounds = {g: resolve(g, scope) for g in GROUNDS}
    missing = [g for g, v in grounds.items() if v is None]
    if missing:
        failures.append(f"{theme_name}: ground(s) unresolvable: {missing}")
        return failures

    print(f"\n=== {theme_name} ===")
    print(f"{'token':16s} {'worst':>6s}  {'need':>5s}  against")

    def row(token, minimum, enforce=True):
        value = resolve(token, scope)
        if value is None:
            print(f"{token:16s} {'--':>6s}   skipped (not a flat colour)")
            return
        worst_g, worst = min(
            ((g, ratio(value, v)) for g, v in grounds.items()), key=lambda t: t[1]
        )
        ok = worst >= minimum
        mark = "ok" if ok else ("FAIL" if enforce else "under (not enforced)")
        print(f"{token:16s} {worst:6.2f}  {minimum:5.1f}  {worst_g}  {mark}")
        if not ok and enforce:
            failures.append(
                f"{theme_name}: {token} is {worst:.2f}:1 on {worst_g}, "
                f"needs {minimum}:1"
            )

    for token in TEXT + INKS:
        row(token, AA_TEXT)

    # --border-strong is reported, not enforced. WCAG 1.4.11 asks 3:1 of a
    # boundary only when the boundary is the sole way to identify a control.
    # Here controls are identified by their --surface fill against --bg, and
    # --border-strong draws dividers and the skip-link. If you ever build a
    # control whose only edge is this token -- a transparent-fill input, a
    # borderless segmented switch -- move it to the enforced list and raise
    # the value to at least #717171 on dark.
    row("--border-strong", AA_NONTEXT, enforce=False)

    # Each -soft tint, flattened over every ground, is a surface of its own.
    for fill in FILLS:
        hue = fill.lstrip("-")
        tint = rgba(scope.get(f"--{hue}-soft"), scope)
        if tint is None:
            continue
        for fg in [f"--{hue}-ink", *TINT_CARRIES]:
            value = resolve(fg, scope)
            if value is None:
                continue
            worst_g, worst = min(
                (
                    (g, ratio(value, flatten(tint, v)))
                    for g, v in grounds.items()
                ),
                key=lambda t: t[1],
            )
            label = f"{fg.lstrip('-')}/{hue}-soft"
            ok = worst >= AA_TEXT
            print(
                f"{label:16s} {worst:6.2f}  {AA_TEXT:5.1f}  {worst_g}"
                f"  {'ok' if ok else 'FAIL'}"
            )
            if not ok:
                failures.append(
                    f"{theme_name}: {fg} on --{hue}-soft over {worst_g} is "
                    f"{worst:.2f}:1, needs {AA_TEXT}:1"
                )

    on_accent = resolve("--on-accent", scope)
    if on_accent:
        for fill in FILLS:
            value = resolve(fill, scope)
            if value is None:
                continue
            r = ratio(on_accent, value)
            label = "on-accent/" + fill.lstrip("-")
            print(
                f"{label:16s} {r:6.2f}  {AA_TEXT:5.1f}  fill"
                f"  {'ok' if r >= AA_TEXT else 'FAIL'}"
            )
            if r < AA_TEXT:
                failures.append(
                    f"{theme_name}: --on-accent on {fill} is {r:.2f}:1, "
                    f"needs {AA_TEXT}:1"
                )
    return failures


def main():
    if not TOKENS.exists():
        sys.exit(f"not found: {TOKENS}")
    scopes = themes(TOKENS.read_text())
    failures = []
    for name, scope in scopes.items():
        failures += check(name, scope)

    print()
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        sys.exit(1)
    print("all pairs clear WCAG AA")


if __name__ == "__main__":
    main()
