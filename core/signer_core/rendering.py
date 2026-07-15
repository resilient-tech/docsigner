"""Rasterize a PDF page for a placement UI, read page sizes in points, and turn
a fractional placement into a PDF-points box.

Shared so every consumer (the desktop app, the opensigner integration) rasterizes
and positions signatures the same way. Rendering needs the optional 'render'
extra (pypdfium2); the import is lazy so `import signer_core` stays light for the
server and host, which never rasterize:

    pip install signer-core[render]
"""

import base64
import io

from .errors import SignerError


def _pdfium():
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise SignerError(
            "INTERNAL",
            "PDF rendering needs the optional 'render' extra: pip install signer-core[render]",
        ) from None
    return pdfium


def _resolve(index: int, n: int) -> int:
    return n - 1 if index < 0 else max(0, min(index, n - 1))


def page_size(path: str, index: int) -> tuple[float, float, int]:
    """(width_pt, height_pt, page_count) for one page; index -1 = last page."""
    pdf = _pdfium().PdfDocument(path)
    try:
        n = len(pdf)
        w, h = pdf[_resolve(index, n)].get_size()
        return float(w), float(h), n
    finally:
        pdf.close()


def render_page(path: str, index: int, width_px: int = 1000) -> dict:
    """Rasterize a page to a JPEG data URL, plus its size in points and index.

    init_forms() paints signature/form-field widgets into the image, so existing
    signatures show in the preview. It is idempotent and a no-op on documents
    without forms.
    """
    pdfium = _pdfium()
    pdf = pdfium.PdfDocument(path)
    try:
        try:
            pdf.init_forms()
        except Exception:
            pass  # XFA or other edge case; render without the form layer
        n = len(pdf)
        i = _resolve(index, n)
        page = pdf[i]
        w_pt, h_pt = page.get_size()
        scale = max(0.2, min(4.0, width_px / float(w_pt)))
        pil = page.render(scale=scale).to_pil().convert("RGB")
        buf = io.BytesIO()
        pil.save(buf, "JPEG", quality=82)
        return {
            "image": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
            "widthPt": float(w_pt),
            "heightPt": float(h_pt),
            "pages": n,
            "page": i,
        }
    finally:
        pdf.close()


def placement_box(fx: float, fy: float, fw: float, fh: float,
                  w_pt: float, h_pt: float) -> list[float]:
    """Fractional top-left placement (0..1) -> [x1, y1, x2, y2] in PDF points.

    Screen space is top-left origin; PDF space is bottom-left. One fractional
    placement maps cleanly onto pages of any size, so a batch shares one box.
    """
    x1 = fx * w_pt
    x2 = (fx + fw) * w_pt
    y_top = h_pt - fy * h_pt
    y_bot = h_pt - (fy + fh) * h_pt
    return [round(x1, 1), round(y_bot, 1), round(x2, 1), round(y_top, 1)]
