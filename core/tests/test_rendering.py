"""placement_box: fractional (top-left) placement -> PDF-points box (bottom-left).

Rasterization (page_size/render_page) needs the optional pypdfium2 extra and a
real PDF, so it is exercised by the desktop app, not here."""

from docsigner_core import placement_box


def test_placement_box_maps_top_left_fraction_to_pdf_points():
    # A4 (595 x 842): a box at the lower-right, top-left origin.
    x1, y1, x2, y2 = placement_box(0.68, 0.86, 0.29, 0.10, 595.0, 842.0)
    assert x1 < x2 and y1 < y2  # well-formed box
    assert (round(x1, 1), round(x2, 1)) == (404.6, 577.1)
    # fy 0.86 from the top -> y2 (top edge) at 842*(1-0.86); +0.10 tall -> y1 below.
    assert round(y2, 1) == 117.9 and round(y1, 1) == 33.7


def test_placement_box_full_page():
    assert placement_box(0.0, 0.0, 1.0, 1.0, 100.0, 200.0) == [0.0, 0.0, 100.0, 200.0]
