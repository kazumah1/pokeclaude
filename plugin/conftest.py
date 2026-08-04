import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "lib"))


@pytest.fixture(autouse=True)
def _isolate_pokedex(monkeypatch, tmp_path):
    """Isolate the Pokédex for every test (reload recomputes store globals AND the
    baked path= defaults from the temp home, so even a bare store call stays here)."""
    d = str(tmp_path / "pokeclaude")
    monkeypatch.setenv("POKECLAUDE_HOME", d)
    from pokeclaude import store
    importlib.reload(store)
    monkeypatch.setattr(store, "ROOT", d)
    monkeypatch.setattr(store, "DEX_PATH", os.path.join(d, "pokedex.json"))
    monkeypatch.setattr(store, "LOCK_PATH", os.path.join(d, "pokedex.json.lock"))
    monkeypatch.setattr(store, "STATE_PATH", os.path.join(d, "state.json"))
    monkeypatch.setattr(store, "CONFIG_PATH", os.path.join(d, "config.json"))
    return d
