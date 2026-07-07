from signer_host import update


def test_version_compare_padding():
    assert update._is_newer("0.2.0", "0.1.0")
    assert update._is_newer("0.1.1", "0.1.0")
    assert update._is_newer("1.0", "0.9.9")
    assert not update._is_newer("0.1.0", "0.1.0")
    assert not update._is_newer("0.1.0", "0.2.0")
    assert not update._is_newer("0.1", "0.1.0")  # 0.1 == 0.1.0 after padding


def test_no_source_configured(monkeypatch):
    monkeypatch.delenv(update.ENV_URL, raising=False)
    monkeypatch.setattr(update, "DEFAULT_UPDATE_URL", "")
    result = update.check_update()
    assert result["updateAvailable"] is False
    assert result["latestVersion"] is None
    assert result["message"] == "no update source configured"
    assert result["currentVersion"] == update.__version__


def test_network_failure_is_soft(monkeypatch):
    monkeypatch.setenv(update.ENV_URL, "http://example.invalid/feed.json")

    def boom(url):
        raise OSError("no route")

    monkeypatch.setattr(update, "_fetch", boom)
    result = update.check_update()
    assert result["updateAvailable"] is False
    assert "could not check" in result["message"]


def test_update_available(monkeypatch):
    monkeypatch.setenv(update.ENV_URL, "http://example/feed.json")
    monkeypatch.setattr(update, "__version__", "0.1.0")
    monkeypatch.setattr(update, "_fetch",
                        lambda url: {"version": "9.9.9", "url": "http://dl"})
    result = update.check_update()
    assert result["updateAvailable"] is True
    assert result["latestVersion"] == "9.9.9"
    assert result["downloadUrl"] == "http://dl"


def test_up_to_date(monkeypatch):
    monkeypatch.setenv(update.ENV_URL, "http://example/feed.json")
    monkeypatch.setattr(update, "__version__", "5.0.0")
    monkeypatch.setattr(update, "_fetch", lambda url: {"version": "5.0.0"})
    result = update.check_update()
    assert result["updateAvailable"] is False
    assert result["message"] == "up to date"
