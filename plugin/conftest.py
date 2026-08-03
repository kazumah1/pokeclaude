import importlib
import os
import sys

import pytest

# Put lib/ on the path so `import pokeclaude.trade` resolves.
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "lib"))


@pytest.fixture(autouse=True)
def _isolate_pokedex(monkeypatch, tmp_path):
    """Every test gets an isolated Pokedex so a gift/claim can never write to the
    real ~/.claude/pokeclaude.

    pokeclaude's store reads POKECLAUDE_HOME at import and bakes DEX_PATH/etc. into
    both module globals AND `path=DEX_PATH` default arguments. Setting the env or
    reassigning the globals after import does NOT rebind those baked defaults, so a
    bare `store.record_catch(id)` (no explicit path=) would still hit the real file.
    We therefore set the env and RELOAD the module, which re-executes it and
    recomputes the globals and the baked defaults from the temp home. The explicit
    setattr calls below are redundant belt-and-suspenders in case a caller reads a
    global live."""
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
