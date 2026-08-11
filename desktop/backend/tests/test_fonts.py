"""Uploaded handwriting faces: what is accepted, what is refused, what is served.

The upload is a trust boundary (bytes and a filename from the UI, written to
disk and later fed to the PDF renderer), so the checks here are the rejections:
a name that collides with a built-in, bytes that are not a font, and a delete
that would take a bundled face with it.

    ./.venv/bin/python -m pytest tests -q      # from desktop/backend
"""

import base64

import pytest
from docsigner_core.appearance import SCRIPT_FONTS

from docsigner_desktop import fonts


@pytest.fixture(autouse=True)
def isolated_fonts_dir(tmp_path, monkeypatch):
    """Point the store at a temporary folder, and leave the registry as found."""
    monkeypatch.setattr(fonts, "FONTS_DIR", tmp_path / "fonts")
    before = dict(SCRIPT_FONTS)
    yield
    SCRIPT_FONTS.clear()
    SCRIPT_FONTS.update(before)


def _real_font_b64() -> str:
    """A bundled face, standing in for whatever the user uploads."""
    return base64.b64encode(SCRIPT_FONTS["caveat"].read_bytes()).decode()


def test_upload_becomes_selectable_under_its_filename():
    slug = fonts.save("My Signature (v2).TTF", _real_font_b64())
    assert slug == "my-signature-v2"
    assert SCRIPT_FONTS[slug].is_file()
    assert {"slug": slug, "label": "My Signature V2", "custom": True} in fonts.listing()


def test_upload_accepts_a_data_url_like_the_signature_image():
    slug = fonts.save("hand.ttf", "data:font/ttf;base64," + _real_font_b64())
    assert slug in SCRIPT_FONTS


def test_non_font_bytes_are_refused_and_nothing_is_left_behind():
    with pytest.raises(fonts.FontError):
        fonts.save("evil.ttf", base64.b64encode(b"not a font at all").decode())
    assert "evil" not in SCRIPT_FONTS
    assert not list(fonts.FONTS_DIR.glob("*")), "a rejected upload must not stay on disk"


@pytest.mark.parametrize("filename", ["great-vibes.ttf", "Poppins.ttf", "...ttf"])
def test_reserved_and_empty_names_are_refused(filename):
    with pytest.raises(fonts.FontError):
        fonts.save(filename, _real_font_b64())


def test_a_bundled_face_cannot_be_deleted():
    with pytest.raises(fonts.FontError):
        fonts.delete("great-vibes")
    assert "great-vibes" in SCRIPT_FONTS


def test_deleting_an_upload_removes_the_file_and_the_choice():
    slug = fonts.save("mine.ttf", _real_font_b64())
    path = SCRIPT_FONTS[slug]
    fonts.delete(slug)
    assert slug not in SCRIPT_FONTS
    assert not path.exists()


def test_only_known_slugs_resolve_to_a_file():
    """path_for backs the /font-file route, so a slug out of a URL must not
    reach anything the registry does not already hold."""
    assert fonts.path_for("great-vibes") == SCRIPT_FONTS["great-vibes"]
    assert fonts.path_for(fonts.DETAIL_FONT_SLUG) is not None
    for unknown in ("../../etc/passwd", "nope", ""):
        assert fonts.path_for(unknown) is None
