"""What the popup says after a run.

The host used to announce the signature the moment the token produced one, which
is halfway: the timestamp and the revocation data are fetched and embedded after
that, and those are what fail. A run whose embed failed still said "Signed 1
document", and the Sign button stayed on "Signing…" long after the popup.

So the count comes from the written files, and the app raises the popup itself.
"""

from types import SimpleNamespace

import pytest

signing = pytest.importorskip(
    "docsigner_desktop.signing", reason="needs the desktop backend's dependencies"
)
host = pytest.importorskip("docsigner_desktop.host")


@pytest.fixture
def spawned(monkeypatch):
    """Capture what would have been spawned, instead of spawning it."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append({"args": args, "env": kwargs.get("env")})
        return SimpleNamespace(stdout='{"result": {"signatures": []}}', stderr="")

    monkeypatch.setattr(host.subprocess, "run", fake_run)
    monkeypatch.setattr(host, "host_binary", lambda: "docsigner-host")
    return calls


def test_the_host_is_told_not_to_announce_the_signature(spawned):
    """Or there are two popups: the host's early one and ours at the end."""
    host.sign_hashes("ab12", [b"\x00" * 32])
    assert spawned[0]["env"]["DOCSIGNER_NO_NOTIFY"] == "1"


def test_our_own_popup_is_not_suppressed_by_that(spawned, monkeypatch):
    """The switch is the user's to set. Ours must not inherit our own gag."""
    monkeypatch.delenv("DOCSIGNER_NO_NOTIFY", raising=False)
    host.notify("Signed 1 document.")
    assert spawned[0]["args"][1:] == ["notify", "Signed 1 document."]
    env = spawned[0]["env"]
    assert env is None or "DOCSIGNER_NO_NOTIFY" not in env


def results(*oks: bool) -> list[dict]:
    return [{"path": f"{i}.pdf", "ok": ok} for i, ok in enumerate(oks)]


@pytest.mark.parametrize(
    "oks,expected",
    [
        ((True,), "Signed 1 document."),
        ((True, True, True), "Signed 3 documents."),
        ((True, False, True), "Signed 2 of 3 documents."),
        ((False,), "Could not sign 1 document."),
        ((False, False), "Could not sign 2 documents."),
    ],
)
def test_the_popup_counts_what_was_written(oks, expected):
    assert signing.outcome(results(*oks)) == expected


def test_a_failed_embed_is_not_reported_as_signed():
    """The exact run in the log: the token signed, then the embed could not
    collect revocation data. Nothing here may call that a signature."""
    failed = [{"path": "a.pdf", "ok": False, "error": "could not collect revocation data"}]
    assert signing.outcome(failed) == "Could not sign 1 document."


def test_a_skipped_file_does_not_count_as_signed():
    mixed = [{"path": "a.pdf", "ok": True}, {"path": "b.pdf", "ok": False, "skipped": True}]
    assert signing.outcome(mixed) == "Signed 1 of 2 documents."
