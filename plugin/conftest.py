import os
import sys
import tempfile
import pytest

# Put lib/ (which contains BOTH the `casino` and `pokeclaude` packages) on the path.
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "lib"))


@pytest.fixture
def casino_home(monkeypatch):
    """Point casino persistence at a throwaway dir so tests never touch ~/.claude."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("CASINO_HOME", d)
        yield d


@pytest.fixture(autouse=True)
def _isolate_pokedex(monkeypatch, tmp_path):
    """Safety net: EVERY test gets an isolated pokedex so a casino win can never
    write to the real ~/.claude/pokeclaude.

    pokeclaude's store bakes ROOT/DEX_PATH/LOCK_PATH/STATE_PATH/CONFIG_PATH at
    import and binds DEX_PATH into `path=DEX_PATH` default args, so setenv alone
    cannot redirect calls made after import. We monkeypatch the module globals:
    the lock/makedirs read ROOT/LOCK_PATH at runtime (so patching them isolates
    locking), and the bridge passes path=store.DEX_PATH explicitly (read live, so
    patching DEX_PATH isolates reads/writes). All five globals exist on the module
    (verified against pokeclaude main), so setattr never raises.
    """
    d = str(tmp_path / "pokeclaude")
    monkeypatch.setenv("POKECLAUDE_HOME", d)
    from pokeclaude import store as dex_store
    monkeypatch.setattr(dex_store, "ROOT", d)
    monkeypatch.setattr(dex_store, "DEX_PATH", os.path.join(d, "pokedex.json"))
    monkeypatch.setattr(dex_store, "LOCK_PATH", os.path.join(d, "pokedex.json.lock"))
    monkeypatch.setattr(dex_store, "STATE_PATH", os.path.join(d, "state.json"))
    monkeypatch.setattr(dex_store, "CONFIG_PATH", os.path.join(d, "config.json"))
    return d


@pytest.fixture
def pokeclaude_home(_isolate_pokedex):
    """Explicit handle to the isolated pokedex dir (the same one the autouse net
    already redirected). Request this in a test that reads/writes the pokedex; the
    isolation itself is guaranteed for every test regardless."""
    return _isolate_pokedex
