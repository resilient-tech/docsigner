"""The token scan in certs.py: its cache, and the hint it derives.

A scan costs a host subprocess, so the caching rules matter: cache what was
found, never cache "nothing found", and let a failed sign clear it. The scan
also carries the reader list, which is what lets an empty certificate list be
explained rather than just reported.

    ./.venv/bin/python -m pytest tests -q      # from desktop/backend
"""

import pytest

from docsigner_desktop import certs


@pytest.fixture(autouse=True)
def clean_cache():
    certs.invalidate_token_cache()
    yield
    certs.invalidate_token_cache()


def _stub_scan(monkeypatch, results):
    """Replace the real scan with one that pops from `results` and counts calls.

    Each result is the (identities, readers) pair the real scan returns.
    """
    calls = []

    def fake():
        calls.append(1)
        return results[min(len(calls) - 1, len(results) - 1)]

    monkeypatch.setattr(certs, "_scan_token_identities", fake)
    return calls


TOKEN = [{"id": "token:abc", "kind": "token", "thumbprint": "abc"}]
NO_READERS: list[dict] = []

# A reader the OS smart-card service sees but no driver claims.
UNCLAIMED = [{"name": "Watchdata WDIND USB CCID Key 0", "token": "WatchData ProxKey",
              "driverFound": False}]
CLAIMED = [{"name": "Watchdata WDIND USB CCID Key 0", "token": "WatchData ProxKey",
            "driverFound": True}]


# ---- cache ----------------------------------------------------------------

def test_found_tokens_are_cached(monkeypatch):
    calls = _stub_scan(monkeypatch, [(TOKEN, CLAIMED)])
    assert certs._token_identities() == TOKEN
    assert certs._token_identities() == TOKEN
    assert len(calls) == 1, "a second look re-scanned instead of using the cache"


def test_empty_scan_is_not_cached(monkeypatch):
    # Someone who just plugged a token in must see it on the next look.
    calls = _stub_scan(monkeypatch, [([], NO_READERS), (TOKEN, CLAIMED)])
    assert certs._token_identities() == []
    assert certs._token_identities() == TOKEN
    assert len(calls) == 2


def test_invalidate_forces_a_rescan(monkeypatch):
    calls = _stub_scan(monkeypatch, [(TOKEN, CLAIMED)])
    certs._token_identities()
    certs.invalidate_token_cache()
    certs._token_identities()
    assert len(calls) == 2


def test_cache_expires(monkeypatch):
    calls = _stub_scan(monkeypatch, [(TOKEN, CLAIMED)])
    certs._token_identities()

    now = [0.0]
    monkeypatch.setattr(certs.time, "monotonic", lambda: now[0])
    certs.invalidate_token_cache()
    certs._token_identities()          # cached at t=0, expires at t=TTL
    now[0] = certs._TOKEN_CACHE_TTL_SECONDS + 1
    certs._token_identities()
    assert len(calls) == 3


def test_readers_come_from_the_same_scan_as_the_identities(monkeypatch):
    """One scan feeds both, so the list and the reason it is empty cannot
    disagree with each other."""
    calls = _stub_scan(monkeypatch, [([], UNCLAIMED)])
    identities, readers = certs._token_scan()
    assert identities == []
    assert readers == UNCLAIMED
    assert len(calls) == 1


# ---- the hint -------------------------------------------------------------

def test_no_hint_when_certificates_were_found(monkeypatch):
    """Nothing to explain: the menu has entries."""
    _stub_scan(monkeypatch, [(TOKEN, UNCLAIMED)])
    assert certs.token_hint() is None


def test_no_hint_when_nothing_is_plugged_in(monkeypatch):
    """An empty list with no reader is not a driver problem, and guessing that
    it is would send people to install software they do not need."""
    _stub_scan(monkeypatch, [([], NO_READERS)])
    assert certs.token_hint() is None


def test_no_hint_when_the_driver_is_installed(monkeypatch):
    """Driver present but no certificates is a different fault, and the sign
    attempt reports it properly. Claiming "install the driver" would be wrong."""
    _stub_scan(monkeypatch, [([], CLAIMED)])
    assert certs.token_hint() is None


def test_hint_names_the_token_when_the_driver_is_missing(monkeypatch):
    _stub_scan(monkeypatch, [([], UNCLAIMED)])
    hint = certs.token_hint()
    assert hint is not None
    assert hint["token"] == "WatchData ProxKey"
    assert "WatchData ProxKey" in hint["message"]
    assert "driver" in hint["message"]
    assert hint["action"]
    assert hint["readers"] == ["Watchdata WDIND USB CCID Key 0"]


def test_hint_still_helps_when_the_model_is_unrecognised(monkeypatch):
    """PC/SC saw a reader but the name matched no known token. Still worth
    saying, since "no certificates found" alone reads as a broken token."""
    unknown = [{"name": "Generic CCID Reader", "token": None, "driverFound": False}]
    _stub_scan(monkeypatch, [([], unknown)])
    hint = certs.token_hint()
    assert hint is not None
    assert hint["token"] is None
    assert "token is connected" in hint["message"]
    assert hint["readers"] == ["Generic CCID Reader"]


def test_hint_ignores_readers_that_already_have_a_driver(monkeypatch):
    """Two readers, one usable: only the unusable one is worth mentioning."""
    mixed = CLAIMED + [{"name": "FEITIAN ePass2003", "token": "Feitian ePass2003",
                        "driverFound": False}]
    _stub_scan(monkeypatch, [([], mixed)])
    hint = certs.token_hint()
    assert hint is not None
    assert hint["token"] == "Feitian ePass2003"
    assert hint["readers"] == ["FEITIAN ePass2003"]


def test_hint_survives_a_host_that_reports_no_readers_key(monkeypatch):
    """Older hosts, and any failure path, omit `readers` entirely."""
    monkeypatch.setattr(certs, "_scan_token_identities", lambda: ([], []))
    assert certs.token_hint() is None
