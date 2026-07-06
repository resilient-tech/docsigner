import types

import pytest

from signer_host import pin
from signer_host.errors import HostError


def test_env_var_wins(monkeypatch):
    monkeypatch.setenv(pin.ENV_VAR, "9999")
    assert pin.get_pin("any token") == "9999"


def test_dialog_cancel_is_user_cancelled(monkeypatch):
    monkeypatch.delenv(pin.ENV_VAR, raising=False)
    monkeypatch.setattr(pin, "_prompt", lambda label: None)
    with pytest.raises(HostError) as err:
        pin.get_pin("token")
    assert err.value.code == "USER_CANCELLED"


def test_no_dialog_available_is_user_cancelled(monkeypatch):
    monkeypatch.delenv(pin.ENV_VAR, raising=False)

    def no_dialog(label):
        raise HostError("USER_CANCELLED", "no PIN dialog available")

    monkeypatch.setattr(pin, "_prompt", no_dialog)
    with pytest.raises(HostError) as err:
        pin.get_pin("token")
    assert err.value.code == "USER_CANCELLED"


def test_prompt_mac_parses_pin_and_cancel(monkeypatch):
    stub = {"stdout": "1234\n"}  # osascript appends a trailing newline

    monkeypatch.setattr(
        pin.subprocess, "run", lambda argv, **kw: types.SimpleNamespace(stdout=stub["stdout"])
    )
    assert pin._prompt_mac("WD PROXKey") == "1234"

    stub["stdout"] = "\n"  # Cancel -> empty text -> None
    assert pin._prompt_mac("WD PROXKey") is None
