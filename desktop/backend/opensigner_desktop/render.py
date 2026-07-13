"""Render a PDF page to an image for the placement canvas, and read page sizes
in points so screen fractions can be turned into PDF coordinates."""

import base64
import io

import pypdfium2 as pdfium


def _resolve(index: int, n: int) -> int:
    return n - 1 if index < 0 else max(0, min(index, n - 1))


def page_size(path: str, index: int) -> tuple[float, float, int]:
    pdf = pdfium.PdfDocument(path)
    try:
        n = len(pdf)
        w, h = pdf[_resolve(index, n)].get_size()
        return float(w), float(h), n
    finally:
        pdf.close()


def render_page(path: str, index: int, width_px: int = 1000) -> dict:
    pdf = pdfium.PdfDocument(path)
    try:
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
