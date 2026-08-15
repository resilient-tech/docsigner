"""What the app opens when it is launched with paths — "Open With", a drag onto
the icon, or a command line."""

import pytest

from docsigner_desktop import startup


@pytest.fixture(autouse=True)
def _clear():
    startup.PATHS.clear()
    yield
    startup.PATHS.clear()


def _pdf(folder, name):
    p = folder / name
    p.write_bytes(b"%PDF-1.7\n")
    return p


def test_flags_are_not_paths():
    startup.remember(["--server", "a.pdf", "-v"])
    assert startup.PATHS == ["a.pdf"]


def test_nothing_opened_is_empty():
    assert startup.listing() == {"folder": None, "files": [], "ignored": []}


def test_one_folder_opens_all_its_pdfs(tmp_path):
    _pdf(tmp_path, "b.pdf")
    _pdf(tmp_path, "a.pdf")
    (tmp_path / "notes.txt").write_text("x")
    startup.remember([str(tmp_path)])
    got = startup.listing()
    assert got["folder"] == str(tmp_path)
    assert [f["name"] for f in got["files"]] == ["a.pdf", "b.pdf"]


def test_several_files_open_as_one_batch(tmp_path):
    a, b = _pdf(tmp_path, "a.pdf"), _pdf(tmp_path, "b.pdf")
    startup.remember([str(a), str(b)])
    got = startup.listing()
    assert [f["name"] for f in got["files"]] == ["a.pdf", "b.pdf"]
    assert got["folder"] == str(tmp_path)
    assert got["files"][0]["size"] == a.stat().st_size


def test_non_pdfs_and_missing_files_are_dropped(tmp_path):
    good = _pdf(tmp_path, "real.pdf")
    (tmp_path / "notes.txt").write_text("x")
    startup.remember([str(good), str(tmp_path / "notes.txt"), str(tmp_path / "gone.pdf")])
    assert [f["name"] for f in startup.listing()["files"]] == ["real.pdf"]


def test_a_non_pdf_is_named_so_the_ui_can_explain(tmp_path):
    """Open with can be pointed at any file type; being handed a .txt must not
    look like the app simply failed to open anything."""
    (tmp_path / "notes.txt").write_text("x")
    startup.remember([str(tmp_path / "notes.txt")])
    got = startup.listing()
    assert got["files"] == []
    assert got["ignored"] == ["notes.txt"]


def test_a_folder_of_pdfs_ignores_nothing(tmp_path):
    _pdf(tmp_path, "a.pdf")
    (tmp_path / "notes.txt").write_text("x")
    startup.remember([str(tmp_path)])
    assert startup.listing()["ignored"] == []
