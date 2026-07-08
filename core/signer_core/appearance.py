"""Signature appearance built from the contract's `appearance` object."""

import base64
import io
from datetime import datetime
from pathlib import Path

from pyhanko.sign.fields import SigFieldSpec
from pyhanko.stamp import TextStampStyle

from .errors import SignerError

DEFAULT_TEXT = "Signed by {signer}\n{ts}"
MARGIN_PT = 24
DEFAULT_SIZE = (200.0, 50.0)
POSITIONS = ("bottom-left", "bottom-right", "top-left", "top-right")

_FONT_DIR = Path(__file__).parent / "fonts"
SCRIPT_FONT = _FONT_DIR / "GreatVibes-Regular.ttf"
TEXT_FONT = _FONT_DIR / "Poppins-Regular.ttf"
_INK = (20, 49, 93)  # navy
_GREY = (95, 99, 108)
_PX_PER_PT = 4  # compose at 4x so the stamp stays crisp in print


def cert_common_name(cert) -> str:
    """CN from an asn1crypto certificate, falling back to the full subject."""
    try:
        return cert.subject.native.get("common_name") or cert.subject.human_friendly
    except Exception:
        return ""


def build_appearance(appearance, field_name: str, writer=None, reason: str | None = None,
                     signer_name: str | None = None):
    """Return (stamp_style, new_field_spec); (None, None) means invisible.

    `writer` (the PDF being signed) is needed only when the appearance uses a
    `position` corner preset instead of an explicit `box`. `reason` fills the
    {reason} placeholder in the stamp text. `signer_name` (usually the
    certificate CN) feeds the handwritten style and {signer} substitution in
    composed stamps.
    """
    if not appearance:
        return None, None

    page = int(appearance.get("page", 0))
    box = _resolve_box(appearance, writer, page)
    spec = SigFieldSpec(
        sig_field_name=field_name,
        on_page=page,
        box=tuple(float(v) for v in box),
    )

    if appearance.get("style") == "handwritten" or appearance.get("qr_url"):
        from pyhanko.pdf_utils.images import PdfImage

        png = _composed_stamp(appearance, box, signer_name, reason)
        style = TextStampStyle(
            stamp_text="", background=PdfImage(png),
            background_opacity=1, border_width=0,
        )
        return style, spec

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
        from pyhanko.pdf_utils.images import PdfImage

        background = PdfImage(_decode_image(image_b64))

    style = TextStampStyle(stamp_text=stamp_text, background=background)
    return style, spec


def _decode_image(image_b64):
    from PIL import Image

    try:
        pil_image = Image.open(io.BytesIO(base64.b64decode(image_b64)))
        pil_image.load()
        return pil_image
    except Exception:
        raise SignerError(
            "DOCUMENT_INVALID", "appearance.image is not a decodable image"
        ) from None


def _composed_stamp(appearance, box, signer_name, reason):
    """One PNG carrying the whole stamp: handwritten name or image, detail
    lines, and an optional QR — full layout control, no font surprises."""
    from PIL import Image, ImageDraw, ImageFont

    w_pt = float(box[2]) - float(box[0])
    h_pt = float(box[3]) - float(box[1])
    if w_pt <= 0 or h_pt <= 0:
        raise SignerError("DOCUMENT_INVALID", "appearance.box has no area")
    W, H = int(w_pt * _PX_PER_PT), int(h_pt * _PX_PER_PT)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    pad = max(2, H // 25)

    # Right side: QR panel, square, full height.
    text_right = W
    qr_url = appearance.get("qr_url")
    if qr_url:
        qr_img = _qr_image(qr_url, H)
        canvas.paste(qr_img, (W - qr_img.width, (H - qr_img.height) // 2))
        text_right = W - qr_img.width - pad
    text_w = text_right - pad
    if text_w <= 0:
        raise SignerError("DOCUMENT_INVALID", "appearance.box too narrow for its QR code")

    # Top area: handwritten name (or a supplied image).
    y = pad
    handwritten = appearance.get("style") == "handwritten"
    lines = _detail_lines(appearance, signer_name, reason, handwritten)
    top_h = int(H * (0.52 if lines else 0.9))
    if handwritten:
        name = appearance.get("name") or signer_name
        if not name:
            raise SignerError(
                "DOCUMENT_INVALID",
                "appearance.style handwritten needs a name or a signer certificate",
            )
        if appearance.get("capitalize", True):
            name = " ".join(w[:1].upper() + w[1:] for w in name.split())
        font, bbox = _fit_text(draw, name, SCRIPT_FONT, text_w, top_h - pad)
        stroke = max(1, font.size // 28) if appearance.get("bold") else 0
        draw.text((pad - bbox[0], y - bbox[1]), name, font=font, fill=_INK,
                  stroke_width=stroke, stroke_fill=_INK)
        y = pad + (bbox[3] - bbox[1]) + pad
    elif appearance.get("image"):
        img = _decode_image(appearance["image"]).convert("RGBA")
        img.thumbnail((text_w, top_h - pad))
        canvas.paste(img, (pad, y), img)
        y = pad + img.height + pad

    # Bottom area: detail lines.
    if lines:
        line_h = max(8, min(int(H * 0.13), (H - y - pad) // len(lines)))
        for line in lines:
            font, bbox = _fit_text(draw, line, TEXT_FONT, text_w, line_h)
            draw.text((pad - bbox[0], y - bbox[1]), line, font=font, fill=_GREY)
            y += int(font.size * 1.25)
    return canvas


def _detail_lines(appearance, signer_name, reason, handwritten):
    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    text = appearance.get("text")
    if text:
        text = (text.replace("{signer}", signer_name or "")
                    .replace("{ts}", ts)
                    .replace("{reason}", reason or ""))
        return [ln for ln in text.splitlines() if ln.strip()]
    if handwritten:
        lines = [f"Digitally signed by {signer_name or appearance.get('name', '')}", ts]
    else:
        lines = [f"Signed by {signer_name or ''}", ts]
    if reason:
        lines.append(reason)
    return [ln for ln in lines if ln.strip()]


def _fit_text(draw, text, font_path, max_w, max_h):
    """Largest font size (descending 10% steps) whose rendering fits the box."""
    from PIL import ImageFont

    size = max(8, max_h)
    while True:
        font = ImageFont.truetype(str(font_path), size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0] <= max_w and bbox[3] - bbox[1] <= max_h) or size <= 8:
            return font, bbox
        size = max(8, int(size * 0.9))


def _qr_image(url, height_px):
    try:
        import qrcode
    except ImportError:
        raise SignerError(
            "INTERNAL", "appearance.qr_url needs the 'qrcode' package installed"
        ) from None
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=1,
                       box_size=10)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="rgb(20,49,93)", back_color="white").convert("RGBA")
    side = max(24, height_px)
    return img.resize((side, side), 0)  # NEAREST keeps modules sharp


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
