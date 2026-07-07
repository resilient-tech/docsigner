import subprocess

from signer_host import notify


def test_notify_never_raises_on_subprocess_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no notify-send")

    monkeypatch.delenv(notify.ENV_DISABLE, raising=False)
    monkeypatch.setattr(subprocess, "run", boom)
    notify.notify("t", "b")  # must not raise


def test_notify_disabled_by_env(monkeypatch):
    called = []
    monkeypatch.setenv(notify.ENV_DISABLE, "1")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    notify.notify("t", "b")
    assert called == []


def test_applescript_string_escapes():
    assert notify._applescript_string('a"b\\c') == '"a\\"b\\\\c"'
