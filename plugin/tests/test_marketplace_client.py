import os
import pytest

from pokeclaude import marketplace_client as mc


def test_no_url_configured_is_dormant(monkeypatch):
    monkeypatch.delenv("POKECLAUDE_MARKET_URL", raising=False)
    from pokeclaude import store
    monkeypatch.setattr(store, "load_config", lambda path=store.CONFIG_PATH: {})
    assert mc.configured() is False
    assert mc.server_url() is None


def test_url_from_env(monkeypatch):
    monkeypatch.setenv("POKECLAUDE_MARKET_URL", "http://127.0.0.1:8787")
    assert mc.server_url() == "http://127.0.0.1:8787"
    assert mc.configured() is True


def test_url_rejects_non_http(monkeypatch):
    monkeypatch.setenv("POKECLAUDE_MARKET_URL", "ftp://nope")
    assert mc.server_url() is None  # invalid -> treated as unconfigured
