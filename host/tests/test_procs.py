"""Competing-process detection: matching, dedup, self-exclusion."""

import os

from signer_host import procs


def test_matches_and_dedupes(monkeypatch):
    monkeypatch.setattr(procs, "_process_list", lambda: [
        (100, "webpki"),
        (101, "etoken.exe"),
        (102, "safenetauthservice"),
        (103, "textedit"),
    ])
    assert procs.competing() == ["a competing signing host", "SafeNet Authentication Client"]


def test_excludes_own_process_tree(monkeypatch):
    monkeypatch.setattr(procs, "_process_list", lambda: [
        (os.getpid(), "opensigner-host"),
        (os.getppid(), "opensigner-host"),
        (999999, "opensigner-host"),
    ])
    assert procs.competing() == ["another OpenSigner host"]


def test_broken_process_list_means_nothing_found(monkeypatch):
    monkeypatch.setattr(procs, "_process_list", lambda: [])
    assert procs.competing() == []
