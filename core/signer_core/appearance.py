"""Signature appearance built from the contract's `appearance` object."""

import base64
import io

from pyhanko.sign.fields import SigFieldSpec
from pyhanko.stamp import TextStampStyle

from .errors import SignerError

DEFAULT_TEXT = "Signed by {signer}\n{ts}"


def build_appearance(appearance, field_name: str):
    """Return (stamp_style, new_field_spec); (None, None) means invisible."""
    if not appearance:
        return None, None

    box = appearance.get("box")
    if not (isinstance(box, (list, tuple)) and len(box) == 4):
        raise SignerError(
            "DOCUMENT_INVALID", "appearance.box must be [x1, y1, x2, y2] in PDF points"
        )
    page = int(appearance.get("page", 0))

    text = appearance.get("text") or DEFAULT_TEXT
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
