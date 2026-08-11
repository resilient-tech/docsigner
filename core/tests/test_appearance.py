"""Corner presets resolved against the real page size, and {reason} in the stamp."""

import io
import shutil

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


def test_title_case_lowers_all_caps_names():
    from signer_core.appearance import title_case

    assert title_case("RAHUL SHARMA") == "Rahul Sharma"
    assert title_case("rahul sharma") == "Rahul Sharma"
    assert title_case("Rahul Sharma") == "Rahul Sharma"


# --- composed stamps: handwritten style and QR panel ---


def test_handwritten_composes_background_and_no_text():
    style, spec = build_appearance(
        {"style": "handwritten", "position": "bottom-right"},
        "Sig1", writer=_writer(), signer_name="Smit Vora",
    )
    assert style.stamp_text == ""
    assert style.background is not None
    assert style.border_width == 0
    assert spec.box == (388.0, 24.0, 588.0, 74.0)


def test_handwritten_needs_a_name():
    with pytest.raises(SignerError) as err:
        build_appearance(
            {"style": "handwritten", "position": "bottom-right"},
            "Sig1", writer=_writer(),
        )
    assert err.value.code == "DOCUMENT_INVALID"


def test_qr_url_composes_even_without_handwritten_style():
    style, _ = build_appearance(
        {"position": "bottom-left", "qr_url": "https://example.com/os_verify?code=x"},
        "Sig1", writer=_writer(), signer_name="Smit Vora",
    )
    assert style.stamp_text == ""
    assert style.background is not None


def test_qr_box_too_narrow_rejected():
    # A square box leaves no room left of the full-height QR panel.
    with pytest.raises(SignerError) as err:
        build_appearance(
            {"box": [0, 0, 50, 50], "qr_url": "https://example.com"},
            "Sig1", writer=_writer(), signer_name="X",
        )
    assert err.value.code == "DOCUMENT_INVALID"


def test_appearance_text_substitution_in_composed_stamp():
    # {signer}/{ts}/{reason} substitution happens at compose time, not pyHanko's.
    style, _ = build_appearance(
        {"position": "top-right", "qr_url": "https://e.co", "text": "By {signer}\n{reason}"},
        "Sig1", writer=_writer(), reason="Approved", signer_name="Smit Vora",
    )
    assert style.background is not None


def test_handwritten_font_choice_accepted():
    """Every bundled slug renders. Reads SCRIPT_FONTS rather than a copy of it,
    so dropping or adding a face cannot leave this list stale."""
    from signer_core.appearance import SCRIPT_FONTS

    assert len(SCRIPT_FONTS) == 5, "five hands, one per personality"
    for font in SCRIPT_FONTS:
        style, _ = build_appearance(
            {"style": "handwritten", "position": "bottom-right", "font": font},
            "Sig1", writer=_writer(), signer_name="Smit Vora",
        )
        assert style.background is not None


def test_register_fonts_adds_a_users_own_face(tmp_path):
    """A registered directory extends the whitelist; the file's stem is the slug.

    Uses a copy of a bundled face as the "uploaded" font, so this checks the
    registration path rather than PIL's tolerance for a synthetic file.
    """
    from signer_core.appearance import SCRIPT_FONTS, register_fonts

    shutil.copy(SCRIPT_FONTS["caveat"], tmp_path / "my-own-hand.ttf")
    (tmp_path / "notes.txt").write_text("not a font")

    try:
        assert register_fonts(tmp_path) == ["my-own-hand"]
        style, _ = build_appearance(
            {"style": "handwritten", "position": "bottom-right", "font": "my-own-hand"},
            "Sig1", writer=_writer(), signer_name="Smit Vora",
        )
        assert style.background is not None
    finally:
        SCRIPT_FONTS.pop("my-own-hand", None)


def test_register_fonts_tolerates_a_missing_directory(tmp_path):
    from signer_core.appearance import register_fonts

    assert register_fonts(tmp_path / "never-created") == []


def test_unknown_handwritten_font_rejected():
    with pytest.raises(SignerError) as err:
        build_appearance(
            {"style": "handwritten", "position": "bottom-right", "font": "comic-sans"},
            "Sig1", writer=_writer(), signer_name="X",
        )
    assert err.value.code == "DOCUMENT_INVALID"
    assert "comic-sans" not in err.value.message  # lists the allowed set instead


def test_negative_page_resolves_to_last():
    # helpers_core's blank PDF has one page: -1 must resolve to index 0.
    _, spec = build_appearance({"position": "bottom-right", "page": -1}, "Sig1", writer=_writer())
    assert spec.on_page == 0


def test_page_before_first_rejected():
    with pytest.raises(SignerError) as err:
        build_appearance({"position": "bottom-right", "page": -2}, "Sig1", writer=_writer())
    assert err.value.code == "DOCUMENT_INVALID"


def _tiny_png_b64() -> str:
    import base64

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (8, 4), (0, 0, 255, 255)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_image_style_composes_stamp():
    # style="image" routes through the composed path: the uploaded image becomes
    # the stamp background, with the detail lines drawn below it.
    style, spec = build_appearance(
        {"style": "image", "box": [0, 0, 200, 50], "image": _tiny_png_b64(),
         "text": "By {signer}"},
        "Sig1", writer=_writer(), signer_name="Smit Vora",
    )
    assert style.background is not None
    assert spec.box == (0.0, 0.0, 200.0, 50.0)


def test_decode_image_accepts_data_url_prefix():
    # The desktop app stores a browser FileReader data: URL as-is; core strips it.
    style, _ = build_appearance(
        {"style": "image", "box": [0, 0, 200, 50],
         "image": "data:image/png;base64," + _tiny_png_b64()},
        "Sig1", writer=_writer(), signer_name="Smit Vora",
    )
    assert style.background is not None
