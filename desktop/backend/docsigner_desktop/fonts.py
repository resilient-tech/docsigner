"""The handwriting the stamp is drawn in. Five we ship, plus whatever gets added.

Five cover most people. The sixth request is always someone's own signature font,
so uploads land in the app's own folder and are registered with core. Preview and
PDF then draw the same file.

An upload is checked by actually loading it with the same code that draws the
stamp. If it loads here, signing cannot trip over it later.
"""

import base64
import binascii
import re

from signer_core.appearance import SCRIPT_FONTS, TEXT_FONT, register_fonts

from .store import FONTS_DIR

# A style name per bundled hand, so the picker offers a look rather than a
# typeface name. Also the "can this be deleted" test: ours cannot.
BUNDLED_LABELS = {
    "great-vibes": "Calligraphy",
    "caveat": "Casual",
    "nanum-pen-script": "Pen",
    "cookie": "Brush",
    "bad-script": "Neat script",
}

# The small print under the signature.
DETAIL_FONT_SLUG = "poppins"

MAX_FONT_BYTES = 4 * 1024 * 1024
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class FontError(ValueError):
    """Upload refused. The message goes straight to the user."""


def load() -> None:
    """Tell core about the user's fonts. Fine to call again and again."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    register_fonts(FONTS_DIR)


def listing() -> list[dict]:
    """Every font you can pick. Rescans first, so one dropped in by hand shows up."""
    load()
    return [
        {
            "slug": slug,
            "label": BUNDLED_LABELS.get(slug) or slug.replace("-", " ").title(),
            "custom": slug not in BUNDLED_LABELS,
        }
        for slug in SCRIPT_FONTS
    ]


def path_for(slug: str):
    """The file behind a name. None if we do not know it.

    Looked up in a list, never treated as a path, because the name came from a URL.
    """
    if slug == DETAIL_FONT_SLUG:
        return TEXT_FONT
    return SCRIPT_FONTS.get(slug)


def slugify(filename: str) -> str:
    """"My Signature (v2).TTF" -> "my-signature-v2". Raises if nothing is left."""
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    slug = _SLUG_RE.sub("-", stem.lower()).strip("-")
    if not slug:
        raise FontError("Give the font file a name with letters or numbers in it.")
    if slug in BUNDLED_LABELS or slug == DETAIL_FONT_SLUG:
        raise FontError(f"'{slug}' is a built-in font name. Rename the file and try again.")
    return slug


def save(filename: str, data_b64: str) -> str:
    """Keep an uploaded font and start using it. Returns its name."""
    slug = slugify(filename)
    try:
        raw = base64.b64decode(data_b64.split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError):
        raise FontError("That upload was not readable.") from None
    if not raw:
        raise FontError("That file is empty.")
    if len(raw) > MAX_FONT_BYTES:
        raise FontError(f"Font files are capped at {MAX_FONT_BYTES // (1024 * 1024)} MB.")

    suffix = ".otf" if raw[:4] == b"OTTO" else ".ttf"
    path = FONTS_DIR / f"{slug}{suffix}"
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    try:
        _check_renderable(path)
    except FontError:
        path.unlink(missing_ok=True)
        raise
    register_fonts(FONTS_DIR)
    return slug


def _check_renderable(path) -> None:
    from PIL import ImageFont

    try:
        ImageFont.truetype(str(path), 24)
    except Exception:
        raise FontError(
            "That file is not a TrueType or OpenType font the stamp can draw."
        ) from None


def delete(slug: str) -> None:
    """Remove an uploaded face. Bundled ones are refused, not silently ignored."""
    if slug in BUNDLED_LABELS or slug == DETAIL_FONT_SLUG:
        raise FontError("Built-in fonts cannot be removed.")
    path = SCRIPT_FONTS.pop(slug, None)
    if path is None:
        raise FontError("No such font.")
    # Only ever delete inside our own folder, whatever the list says.
    if path.parent == FONTS_DIR:
        path.unlink(missing_ok=True)
