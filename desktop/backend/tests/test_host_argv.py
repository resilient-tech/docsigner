"""How the app decides which host binary to spawn.

The env override is what lets the Rust host be tested against the real app, so
it has to win over both other branches. Reordering these silently breaks that.
"""

import sys

from opensigner_desktop import host


def test_override_wins_over_source(monkeypatch):
    monkeypatch.setenv(host.ENV_HOST_BIN, "/opt/opensigner-host")
    assert host._host_argv() == ["/opt/opensigner-host"]


def test_override_wins_over_frozen(monkeypatch):
    monkeypatch.setenv(host.ENV_HOST_BIN, "/opt/opensigner-host")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert host._host_argv() == ["/opt/opensigner-host"]


def test_frozen_reexecs_itself(monkeypatch):
    monkeypatch.delenv(host.ENV_HOST_BIN, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert host._host_argv() == [sys.executable, "--host-cli"]


def test_source_runs_the_module(monkeypatch):
    monkeypatch.delenv(host.ENV_HOST_BIN, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert host._host_argv() == [sys.executable, "-m", "signer_host.cli"]
