"""Signature appearance built from the contract's `appearance` object."""

import base64
import io

from pyhanko.sign.fields import SigFieldSpec
from pyhanko.stamp import TextStampStyle

from .errors import SignerError

DEFAULT_TEXT = "Signed by {signer}\n{ts}"
MARGIN_PT = 24
DEFAULT_SIZE = (200.0, 50.0)
POSITIONS = ("bottom-left", "bottom-right", "top-left", "top-right")


def build_appearance(appearance, field_name: str, writer=None, reason: str | None = None):
    """Return (stamp_style, new_field_spec); (None, None) means invisible.

    `writer` (the PDF being signed) is needed only when the appearance uses a
    `position` corner preset instead of an explicit `box`. `reason` fills the
    {reason} placeholder in the stamp text.
    """
    if not appearance:
        return None, None

    page = int(appearance.get("page", 0))
    box = _resolve_box(appearance, writer, page)

    text = appearance.get("text") or DEFAULT_TEXT
    text = text.replace("{reason}", reason or "")
    # pyHanko interpolates %(signer)s / %(ts)s; the contract uses {signer} / {ts}.
    stamp_text = (
        text.replace("%", "%%")
        .replace("{signer}", "%(signer)s")
        .replace("{ts}", "%(ts)s")
    )

    background = None
    image_b64 = appearance.get("image")
    if image_b64:
        from PIL import Image
        from pyhanko.pdf_utils.images import PdfImage

        try:
            pil_image = Image.open(io.BytesIO(base64.b64decode(image_b64)))
            pil_image.load()
        except Exception:
            raise SignerError(
                "DOCUMENT_INVALID", "appearance.image is not a decodable image"
            ) from None
        background = PdfImage(pil_image)

    style = TextStampStyle(stamp_text=stamp_text, background=background)
    spec = SigFieldSpec(
        sig_field_name=field_name,
        on_page=page,
        box=tuple(float(v) for v in box),
    )
    return style, spec


def _resolve_box(appearance, writer, page):
    """The explicit box, or one computed from a corner preset and the real page size."""
    box = appearance.get("box")
    if box is not None:
        if not (isinstance(box, (list, tuple)) and len(box) == 4):
            raise SignerError(
                "DOCUMENT_INVALID", "appearance.box must be [x1, y1, x2, y2] in PDF points"
            )
        return box

    position = appearance.get("position")
    if position not in POSITIONS:
        raise SignerError(
            "DOCUMENT_INVALID",
            "appearance needs a box, or a position out of: " + ", ".join(POSITIONS),
        )
    size = appearance.get("size") or DEFAULT_SIZE
    if not (isinstance(size, (list, tuple)) and len(size) == 2):
        raise SignerError("DOCUMENT_INVALID", "appearance.size must be [width, height]")
    width, height = (float(v) for v in size)

    x1, y1, x2, y2 = _media_box(writer, page)
    left, right = x1 + MARGIN_PT, x2 - MARGIN_PT
    bottom, top = y1 + MARGIN_PT, y2 - MARGIN_PT
    bx = (left, left + width) if "left" in position else (right - width, right)
    by = (bottom, bottom + height) if "bottom" in position else (top - height, top)
    return [bx[0], by[0], bx[1], by[1]]


def _media_box(writer, page):
    """The page's MediaBox (inherited if needed) as 4 floats."""
    if writer is None:
        raise SignerError("INTERNAL", "appearance.position needs the document to be loaded")
    try:
        node_ref, kid_ix, _container = writer.find_page_container(page)
        page_obj = node_ref.get_object()["/Kids"][kid_ix].get_object()
        media_box = page_obj.get("/MediaBox")
        while media_box is None and page_obj.get("/Parent") is not None:
            page_obj = page_obj["/Parent"].get_object()
            media_box = page_obj.get("/MediaBox")
        return tuple(float(v) for v in media_box)
    except SignerError:
        raise
    except Exception:
        raise SignerError(
            "DOCUMENT_INVALID", f"appearance.page {page} not found in the document"
        ) from None
