"""On-disk state, safe across concurrent Claude sessions.

Mirrors pokeclaude's store: every mutation goes through transaction(), which
takes an O_EXCL lockfile, re-reads inside the lock, mutates in place, and swaps
via same-directory atomic rename. Readers never lock (rename is atomic). Any
failure to lock degrades to "skip the write" rather than hanging a turn.
"""
import errno
import json
import os
import tempfile
import time

from casino import bankroll

SCHEMA = 1
LOCK_TIMEOUT_S = 2.0
LOCK_STALE_S = 30.0


def root():
    return os.environ.get(
        "CASINO_HOME",
        os.path.join(os.path.expanduser("~"), ".claude", "claude-casino"),
    )


def _state_path():
    return os.path.join(root(), "state.json")


def _lock_path():
    return os.path.join(root(), "state.json.lock")


def frame_path():
    return os.path.join(root(), "last_frame.ans")


def _empty():
    return {
        "schema": SCHEMA,
        "bankroll": bankroll.START_STAKE,
        "config": bankroll.default_config(),
        "stats": {"hands": 0, "wins": 0, "biggest_pot": 0, "net": 0},
        "game": None,
        "last_turn": None,
    }


def _normalize(data):
    if not isinstance(data, dict) or "bankroll" not in data:
        return _empty()
    base = _empty()
    base.update(data)
    # Backfill any missing config/stats keys without dropping saved values.
    cfg = bankroll.default_config()
    cfg.update(base.get("config") or {})
    base["config"] = cfg
    stats = {"hands": 0, "wins": 0, "biggest_pot": 0, "net": 0}
    stats.update(base.get("stats") or {})
    base["stats"] = stats
    return base


def load(path=None):
    path = path or _state_path()
    try:
        with open(path) as f:
            data = json.load(f)
    except (IOError, OSError):
        return _empty()
    except ValueError:
        try:
            os.rename(path, "%s.corrupt-%d" % (path, int(time.time())))
        except OSError:
            pass
        return _empty()
    return _normalize(data)


def _acquire(timeout=LOCK_TIMEOUT_S):
    os.makedirs(root(), exist_ok=True)
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(_lock_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            return fd
        except OSError as e:
            if e.errno != errno.EEXIST:
                return None
            try:
                if time.time() - os.path.getmtime(_lock_path()) > LOCK_STALE_S:
                    os.unlink(_lock_path())
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                return None
            time.sleep(0.02)


def _release(fd):
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(_lock_path())
    except OSError:
        pass


def transaction(mutator):
    """Lock, re-read, mutate in place, atomically swap. None if lock failed."""
    fd = _acquire()
    if fd is None:
        return None
    try:
        state = load()
        mutator(state)
        state["schema"] = SCHEMA
        d = root()
        tmp_fd, tmp_path = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(state, f)
        os.replace(tmp_path, _state_path())
        return state
    finally:
        _release(fd)


def write_frame(text):
    os.makedirs(root(), exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=root(), suffix=".ans")
    with os.fdopen(tmp_fd, "w") as f:
        f.write(text)
    os.replace(tmp_path, frame_path())
