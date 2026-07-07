"""PDF/A detection.

Signing a PDF/A file with an invisible signature preserves conformance (an
incremental update touches nothing the standard constrains). A visible stamp
does not: pyHanko's text stamps use an unembedded standard font, which PDF/A
forbids. Detection lets the API say so instead of silently downgrading a file.
"""

import io
import re

from pyhanko.pdf_utils.reader import PdfFileReader

_PART = re.compile(rb"pdfaid:part(?:>\s*|=\s*[\"'])(\d+)")
_CONFORMANCE = re.compile(rb"pdfaid:conformance(?:>\s*|=\s*[\"'])([A-Ua-u])")


def parse_xmp_pdfa(xmp: bytes):
    """PDF/A identification from raw XMP, element or attribute form; None if absent."""
    part = _PART.search(xmp)
    if not part:
        return None
    conformance = _CONFORMANCE.search(xmp)
    return {
        "part": int(part.group(1)),
        "conformance": conformance.group(1).decode().upper() if conformance else None,
    }


def detect_pdfa(pdf_bytes: bytes):
    """PDF/A claim of a document per its XMP metadata; None when not PDF/A."""
    try:
        reader = PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
        metadata = reader.root["/Metadata"].data
    except Exception:
        return None
    return parse_xmp_pdfa(metadata)
