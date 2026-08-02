from casino import store, bankroll


def test_fresh_state_defaults(casino_home):
    state = store.load()
    assert state["bankroll"] == bankroll.START_STAKE
    assert state["config"] == bankroll.default_config()
    assert state["game"] is None
    assert state["stats"] == {"hands": 0, "wins": 0, "biggest_pot": 0, "net": 0}


def test_transaction_persists(casino_home):
    def spend(s):
        s["bankroll"] -= 250
    store.transaction(spend)
    assert store.load()["bankroll"] == bankroll.START_STAKE - 250


def test_corrupt_file_reads_as_fresh(casino_home):
    import os
    path = os.path.join(casino_home, "state.json")
    with open(path, "w") as f:
        f.write("{not valid json")
    state = store.load()
    assert state["bankroll"] == bankroll.START_STAKE


def test_write_and_read_frame(casino_home):
    store.write_frame("\x1b[38;2;1;2;3m▀\x1b[0m")
    with open(store.frame_path()) as f:
        assert "▀" in f.read()
