"""How the app finds the host binary.

The host is a separate Rust executable, so "where is it" is the one thing that
can silently break a packaged build while every unit test still passes.
"""

import sys

import pytest

from opensigner_desktop import host


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    """Most tests need the search itself, not an override of it."""
    monkeypatch.delenv(host.ENV_HOST_BIN, raising=False)


def test_override_wins_over_everything(monkeypatch):
    monkeypatch.setenv(host.ENV_HOST_BIN, "/opt/opensigner-host")
    assert host._host_argv() == ["/opt/opensigner-host"]

    # Even in a frozen build, where a bundled sidecar would otherwise be found.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert host._host_argv() == ["/opt/opensigner-host"]


def test_frozen_looks_beside_the_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    binary = tmp_path / host.BINARY_NAME
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    assert host._host_argv() == [str(binary)]


def test_from_source_finds_the_cargo_build(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    candidates = host._candidates()
    assert candidates, "the source layout must yield somewhere to look"
    assert all(c.name == host.BINARY_NAME for c in candidates)
    # release before debug: a stale debug build must not shadow a fresh release.
    assert "release" in str(candidates[0])
    assert "debug" in str(candidates[1])
    assert candidates[0].parents[2].name == "host-rs"


def test_a_missing_binary_is_a_setup_error_not_a_token_error(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(host, "_candidates", lambda: [])
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    with pytest.raises(host.HostNotFound) as err:
        host.host_binary()
    assert "cargo build" in str(err.value)
    # Still a TokenError, so existing callers keep catching it.
    assert isinstance(err.value, host.TokenError)


def test_listing_degrades_to_empty_when_the_host_is_missing(monkeypatch):
    """The certificate menu shows nothing rather than crashing the app."""
    monkeypatch.setattr(host, "_candidates", lambda: [])
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    assert host.list_certificates() == []


def test_signing_surfaces_a_missing_host(monkeypatch):
    """Signing must not swallow it: the user needs to know why nothing happened."""
    monkeypatch.setattr(host, "_candidates", lambda: [])
    monkeypatch.setattr(host.shutil, "which", lambda _name: None)
    with pytest.raises(host.HostNotFound):
        host.sign_hashes("abcd", [b"0" * 32])


def test_binary_name_matches_the_platform():
    if sys.platform == "win32":
        assert host.BINARY_NAME.endswith(".exe")
    else:
        assert not host.BINARY_NAME.endswith(".exe")
