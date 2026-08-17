"""Turn a page into a picture, and a spot on that picture into a spot on the page.

Lives here so every app that lets you place a signature places it the same way.
Needs the optional extra: `pip install docsigner-core[render]`. The import is lazy,
so the server and host stay light.
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
            "PDF rendering needs the optional 'render' extra: pip install docsigner-core[render]",
        ) from None
    return pdfium


def _resolve(index: int, n: int) -> int:
    return n - 1 if index < 0 else max(0, min(index, n - 1))


def _open(path: str):
    """Open a PDF, or say plainly why it could not be opened.

    pdfium answers in its own terms — "Failed to load document (PDFium: Incorrect
    password error)", "(PDFium: Data format error)" — and none of those are
    sentences to put in front of anyone. There are only three answers worth
    giving: it is locked, it is not readable as a PDF, or it is not there.

    pdfium's wording stays on the raised error as its cause, for the log.

    Both readers below come through here, so a preview and a signing run give the
    same answer about the same file.
    """
    pdfium = _pdfium()
    try:
        return pdfium.PdfDocument(path)
    except FileNotFoundError as exc:
        raise SignerError("DOCUMENT_INVALID", "This file is no longer there.") from exc
    except pdfium.PdfiumError as exc:
        locked = "password" in str(exc).lower()
        raise SignerError(
            "DOCUMENT_INVALID",
            "This PDF is password-protected. DocSigner cannot open it yet."
            if locked
            else "This file is damaged, or it is not a PDF.",
        ) from exc


def page_size(path: str, index: int) -> tuple[float, float, int]:
    """(width_pt, height_pt, page_count) for one page; index -1 = last page."""
    pdf = _open(path)
    try:
        n = len(pdf)
        w, h = pdf[_resolve(index, n)].get_size()
        return float(w), float(h), n
    finally:
        pdf.close()


def render_page(path: str, index: int, width_px: int = 1000) -> dict:
    """Page to a JPEG data URL, with its size and index.

    Form widgets are painted in too, so signatures already on the page show up.
    """
    pdf = _open(path)
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
    """A spot on the screen to a box on the page.

    Screens count down from the top, PDFs count up from the bottom. Keeping the
    spot as a fraction is what lets one placement fit every page size in a batch.
    """
    x1 = fx * w_pt
    x2 = (fx + fw) * w_pt
    y_top = h_pt - fy * h_pt
    y_bot = h_pt - (fy + fh) * h_pt
    return [round(x1, 1), round(y_bot, 1), round(x2, 1), round(y_top, 1)]
