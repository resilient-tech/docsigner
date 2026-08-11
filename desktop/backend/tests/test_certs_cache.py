"""The token-identity cache in certs.py.

A scan costs a host subprocess, so the caching rules matter: cache what was
found, never cache "nothing found", and let a failed sign clear it.

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
    """Replace the real scan with one that pops from `results` and counts calls."""
    calls = []

    def fake():
        calls.append(1)
        return results[min(len(calls) - 1, len(results) - 1)]

    monkeypatch.setattr(certs, "_scan_token_identities", fake)
    return calls


TOKEN = [{"id": "token:abc", "kind": "token", "thumbprint": "abc"}]


def test_found_tokens_are_cached(monkeypatch):
    calls = _stub_scan(monkeypatch, [TOKEN])
    assert certs._token_identities() == TOKEN
    assert certs._token_identities() == TOKEN
    assert len(calls) == 1, "a second look re-scanned instead of using the cache"


def test_empty_scan_is_not_cached(monkeypatch):
    # Someone who just plugged a token in must see it on the next look.
    calls = _stub_scan(monkeypatch, [[], TOKEN])
    assert certs._token_identities() == []
    assert certs._token_identities() == TOKEN
    assert len(calls) == 2


def test_invalidate_forces_a_rescan(monkeypatch):
    calls = _stub_scan(monkeypatch, [TOKEN])
    certs._token_identities()
    certs.invalidate_token_cache()
    certs._token_identities()
    assert len(calls) == 2


def test_cache_expires(monkeypatch):
    calls = _stub_scan(monkeypatch, [TOKEN])
    certs._token_identities()

    now = [0.0]
    monkeypatch.setattr(certs.time, "monotonic", lambda: now[0])
    certs.invalidate_token_cache()
    certs._token_identities()          # cached at t=0, expires at t=TTL
    now[0] = certs._TOKEN_CACHE_TTL_SECONDS + 1
    certs._token_identities()
    assert len(calls) == 3
