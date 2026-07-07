"""Corner presets resolved against the real page size, and {reason} in the stamp."""

import io

import pytest
from helpers_core import make_blank_pdf
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

from signer_core.appearance import build_appearance
from signer_core.errors import SignerError


def _writer():
    # helpers_core's blank page is US Letter: MediaBox [0 0 612 792].
    return IncrementalPdfFileWriter(io.BytesIO(make_blank_pdf()), strict=False)


def test_position_bottom_right_uses_page_size():
    _, spec = build_appearance({"position": "bottom-right"}, "Sig1", writer=_writer())
    assert spec.box == (388.0, 24.0, 588.0, 74.0)  # 612-24-200 .. 612-24, 24 .. 24+50


def test_position_top_left_custom_size():
    _, spec = build_appearance(
        {"position": "top-left", "size": [100, 40]}, "Sig1", writer=_writer()
    )
    assert spec.box == (24.0, 728.0, 124.0, 768.0)


def test_explicit_box_wins_over_position():
    _, spec = build_appearance(
        {"box": [1, 2, 3, 4], "position": "top-left"}, "Sig1", writer=_writer()
    )
    assert spec.box == (1.0, 2.0, 3.0, 4.0)


def test_unknown_position_rejected():
    with pytest.raises(SignerError) as err:
        build_appearance({"position": "center"}, "Sig1", writer=_writer())
    assert err.value.code == "DOCUMENT_INVALID"


def test_missing_page_rejected():
    with pytest.raises(SignerError) as err:
        build_appearance({"position": "top-left", "page": 9}, "Sig1", writer=_writer())
    assert err.value.code == "DOCUMENT_INVALID"


def test_reason_substituted_into_text():
    style, _ = build_appearance(
        {"box": [0, 0, 10, 10], "text": "By {signer}: {reason}"}, "Sig1", reason="Approved"
    )
    assert "Approved" in style.stamp_text
    assert "%(signer)s" in style.stamp_text  # pyHanko placeholders survive
