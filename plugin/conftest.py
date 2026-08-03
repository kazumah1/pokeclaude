import os
import sys

import pytest

# Put lib/ on the path so `import pokeclaude.trade` resolves.
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "lib"))


@pytest.fixture(autouse=True)
def _isolate_pokedex(monkeypatch, tmp_path):
    """Every test gets an isolated Pokedex so a gift/claim can never write to the
    real ~/.claude/pokeclaude. store bakes ROOT/DEX_PATH/STATE_PATH into path=
    defaults at import, so we monkeypatch the module globals (not just setenv)."""
    d = str(tmp_path / "pokeclaude")
    monkeypatch.setenv("POKECLAUDE_HOME", d)
    from pokeclaude import store
    monkeypatch.setattr(store, "ROOT", d)
    monkeypatch.setattr(store, "DEX_PATH", os.path.join(d, "pokedex.json"))
    monkeypatch.setattr(store, "LOCK_PATH", os.path.join(d, "pokedex.json.lock"))
    monkeypatch.setattr(store, "STATE_PATH", os.path.join(d, "state.json"))
    monkeypatch.setattr(store, "CONFIG_PATH", os.path.join(d, "config.json"))
    return d
