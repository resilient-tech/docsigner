"""Checks for the tiny .env loader in config.py."""

import os

from docsigner_server.config import load_dotenv


def test_load_dotenv_sets_and_respects_precedence(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        'QUOTED="quoted value"\n'
        "PLAIN=plain\n"
        "ALREADY=from_file\n"
        "no_equals_sign_here\n"
    )
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.delenv("PLAIN", raising=False)
    monkeypatch.setenv("ALREADY", "from_env")  # real env must win

    load_dotenv(str(env))

    assert os.environ["QUOTED"] == "quoted value"  # quotes stripped
    assert os.environ["PLAIN"] == "plain"
    assert os.environ["ALREADY"] == "from_env"  # not overridden


def test_load_dotenv_missing_file_is_noop(tmp_path):
    load_dotenv(str(tmp_path / "does-not-exist"))  # must not raise
