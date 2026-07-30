"""Pokedex persistence, shared across every Claude Code instance.

All state lives in ~/.claude/pokeclaude/. Several Claude sessions run in
parallel and each has its own hook process, so every mutation goes through
`transaction()`, which takes an O_EXCL lockfile, re-reads the file inside the
lock, applies the caller's change, and swaps the result in via a same-directory
rename. Readers never lock: rename is atomic, so a reader either sees the whole
old file or the whole new one, never a half-written mix.

The lock is deliberately crude. A stale lock (hard-killed process) is broken
after LOCK_STALE_S, and any failure to acquire it degrades to "skip this
write" rather than blocking a user's turn -- dropping one catch is fine, hanging
someone's terminal is not.
"""
import errno
import json
import os
import random
import tempfile
import time

HOME = os.path.expanduser("~")
ROOT = os.environ.get(
    "POKECLAUDE_HOME", os.path.join(HOME, ".claude", "pokeclaude")
)
DEX_PATH = os.path.join(ROOT, "pokedex.json")
LOCK_PATH = os.path.join(ROOT, "pokedex.json.lock")
STATE_PATH = os.path.join(ROOT, "state.json")

LOCK_TIMEOUT_S = 2.0  # give up rather than delay the user's turn
LOCK_STALE_S = 30.0  # assume a lock older than this belongs to a dead process
SCHEMA = 1


def _empty():
    return {"schema": SCHEMA, "caught": {}, "totals": {"encounters": 0, "catches": 0}}


def load(path=DEX_PATH):
    """Read the pokedex. Never raises -- a corrupt file reads as empty.

    A corrupt file is preserved as .corrupt-<ts> instead of being clobbered, so
    a bad write can be inspected rather than silently losing a collection.
    """
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
    if not isinstance(data, dict) or "caught" not in data:
        return _empty()
    data.setdefault("schema", SCHEMA)
    data.setdefault("totals", {"encounters": 0, "catches": 0})
    return data


def _acquire(timeout=LOCK_TIMEOUT_S):
    os.makedirs(ROOT, exist_ok=True)
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            return fd
        except OSError as e:
            if e.errno != errno.EEXIST:
                return None
            try:  # break a lock left behind by a killed process
                if time.time() - os.path.getmtime(LOCK_PATH) > LOCK_STALE_S:
                    os.unlink(LOCK_PATH)
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                return None
            time.sleep(random.uniform(0.01, 0.04))  # jitter: avoid lockstep retries


def _release(fd):
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(LOCK_PATH)
    except OSError:
        pass


def _write_atomic(path, data):
    """Write via temp file + rename so readers never observe a partial file."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, separators=(",", ":"), sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, path)  # atomic within a filesystem
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def transaction(mutate, path=DEX_PATH):
    """Apply `mutate(dex)` under the lock. Returns its result, or None if the
    lock could not be taken (in which case nothing was written)."""
    fd = _acquire()
    if fd is None:
        return None
    try:
        dex = load(path)
        result = mutate(dex)
        _write_atomic(path, dex)
        return result
    finally:
        _release(fd)


def record_catch(species_id, session_id=None, path=DEX_PATH):
    """Persist a catch. Returns a dict describing what changed, or None if the
    write was skipped. `is_new` distinguishes a first capture from a duplicate.
    """
    key = str(int(species_id))
    now = int(time.time())

    def _mutate(dex):
        caught = dex["caught"]
        entry = caught.get(key)
        if entry is None:
            caught[key] = {
                "count": 1,
                "first": now,
                "last": now,
                "first_session": session_id,
            }
            is_new = True
        else:
            entry["count"] = entry.get("count", 0) + 1
            entry["last"] = now
            is_new = False
        dex["totals"]["catches"] = dex["totals"].get("catches", 0) + 1
        return {
            "is_new": is_new,
            "count": caught[key]["count"],
            "unique": len(caught),
        }

    return transaction(_mutate, path)


def caught_ids(path=DEX_PATH):
    return set(int(k) for k in load(path).get("caught", {}))


# --- per-session roll bookkeeping -------------------------------------------
# Kept separate from the pokedex: it is disposable, rewritten constantly, and
# must never risk the integrity of the collection itself.


def load_state(path=STATE_PATH):
    try:
        with open(path) as f:
            s = json.load(f)
            return s if isinstance(s, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def save_state(state, path=STATE_PATH):
    try:
        _write_atomic(path, state)
        return True
    except (IOError, OSError):
        return False
