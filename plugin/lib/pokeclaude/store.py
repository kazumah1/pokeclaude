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
CONFIG_PATH = os.path.join(ROOT, "config.json")

LOCK_TIMEOUT_S = 2.0  # give up rather than delay the user's turn
LOCK_STALE_S = 30.0  # assume a lock older than this belongs to a dead process
MAX_SESSIONS = 200  # cap state.json growth; oldest-progress entries are dropped
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


def project_key(cwd=None):
    """Stable identifier for the project a catch happened in.

    The hook only knows a working directory, so "project" means exactly that:
    the git toplevel if there is one (so subdirectories of a repo share a
    Pokedex), otherwise the directory itself.
    """
    d = os.path.abspath(cwd or os.getcwd())
    probe = d
    while True:
        if os.path.isdir(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return d
        probe = parent


def record_catch(species_id, session_id=None, path=DEX_PATH, project=None,
                 shiny=False):
    """Persist a catch. Returns a dict describing what changed, or None if the
    write was skipped. `is_new` distinguishes a first capture from a duplicate.

    Per-project counts are recorded alongside the global ones so a project view
    can show what was caught while working there. The global collection stays
    the single source of truth; project data is strictly additive bookkeeping.

    Shininess is tracked per species as an additive counter, never as a flag on
    the species itself. Someone who owns a normal Pikachu and later catches a
    shiny one has caught both, and the entry has to be able to say so -- a boolean
    would silently overwrite that history, and `is_new_shiny` would be
    unanswerable. Absent keys mean zero, so pre-shiny Pokedexes stay valid without
    a migration.
    """
    key = str(int(species_id))
    now = int(time.time())

    def _mutate(dex):
        caught = dex["caught"]
        entry = caught.get(key)
        if entry is None:
            entry = caught[key] = {
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

        is_new_shiny = False
        if shiny:
            had = entry.get("shiny", 0)
            entry["shiny"] = had + 1
            is_new_shiny = had == 0
            if not entry.get("shiny_first"):
                entry["shiny_first"] = now
            dex["totals"]["shinies"] = dex["totals"].get("shinies", 0) + 1

        dex["totals"]["catches"] = dex["totals"].get("catches", 0) + 1

        if project:
            projects = dex.setdefault("projects", {})
            p = projects.setdefault(project, {"caught": {}, "catches": 0})
            p["caught"][key] = p["caught"].get(key, 0) + 1
            p["catches"] = p.get("catches", 0) + 1
            if shiny:
                p["shinies"] = p.get("shinies", 0) + 1

        return {
            "is_new": is_new,
            "count": entry["count"],
            "unique": len(caught),
            "shiny": bool(shiny),
            "shiny_count": entry.get("shiny", 0),
            "is_new_shiny": is_new_shiny,
            "project_count": (
                dex.get("projects", {}).get(project, {}).get("caught", {}).get(key)
                if project
                else None
            ),
        }

    return transaction(_mutate, path)


def caught_ids(path=DEX_PATH):
    return set(int(k) for k in load(path).get("caught", {}))


def mark_unseen(species_id, path=DEX_PATH):
    """Record that a catch happened without the user being shown it.

    Some hosts discard hook output, so the banner never reaches the screen there.
    The catch is still real; it just has to be announced the next time the Pokedex
    is opened, which is what this list drives.
    """
    key = str(int(species_id))

    def _mutate(dex):
        pending = dex.setdefault("unseen", [])
        if key not in pending:
            pending.append(key)
        return len(pending)

    return transaction(_mutate, path)


def take_unseen(path=DEX_PATH):
    """Return the unseen catches and clear them, so they are announced once."""

    def _mutate(dex):
        pending = list(dex.get("unseen") or [])
        dex["unseen"] = []
        return pending

    return transaction(_mutate, path) or []


def project_view(dex, project):
    """Reduce a full pokedex to only what was caught in `project`.

    Returns entries shaped like the global ones so renderers need no special
    casing, but with per-project counts. Global first/last timestamps are kept
    since per-project timestamps are not tracked.
    """
    pdata = (dex.get("projects") or {}).get(project) or {"caught": {}, "catches": 0}
    out = {}
    for key, count in (pdata.get("caught") or {}).items():
        g = (dex.get("caught") or {}).get(key) or {}
        entry = {
            "count": count,
            "first": g.get("first", 0),
            "last": g.get("last", 0),
        }
        # Carry the shiny facts through. Per-project shiny counts are not tracked,
        # so this is the global count -- but dropping the key entirely would make
        # `--project --shiny` return nothing and hide shiny colours in the project
        # grid, which is worse than a count that is not project-scoped.
        if g.get("shiny"):
            entry["shiny"] = g["shiny"]
            if g.get("shiny_first"):
                entry["shiny_first"] = g["shiny_first"]
        out[key] = entry
    return out, pdata.get("catches", 0)


def release(species_id=None, path=DEX_PATH, project=None):
    """Remove one species, or every species, from the Pokedex.

    `species_id=None` clears everything. When `project` is set only that
    project's records are cleared and the global collection is left intact --
    resetting one project's luck should never cost someone their collection.

    Returns a dict describing what was removed, or None if the lock was
    unavailable (in which case nothing changed).
    """
    key = None if species_id is None else str(int(species_id))

    def _mutate(dex):
        if project:
            projects = dex.setdefault("projects", {})
            p = projects.get(project) or {"caught": {}, "catches": 0}
            if key is None:
                removed = dict(p.get("caught") or {})
                projects.pop(project, None)
            else:
                removed = {}
                if key in (p.get("caught") or {}):
                    removed[key] = p["caught"].pop(key)
                    p["catches"] = max(0, p.get("catches", 0) - removed[key])
            return {
                "scope": "project",
                "removed": removed,
                "species": len(removed),
                "catches": sum(removed.values()),
            }

        caught = dex["caught"]
        if key is None:
            removed = {k: v.get("count", 1) for k, v in caught.items()}
            dex["caught"] = {}
            dex["totals"]["catches"] = 0
            dex["projects"] = {}
        else:
            removed = {}
            if key in caught:
                removed[key] = caught[key].get("count", 1)
                del caught[key]
                dex["totals"]["catches"] = max(
                    0, dex["totals"].get("catches", 0) - removed[key]
                )
                for p in (dex.get("projects") or {}).values():
                    n = (p.get("caught") or {}).pop(key, 0)
                    p["catches"] = max(0, p.get("catches", 0) - n)
        return {
            "scope": "global",
            "removed": removed,
            "species": len(removed),
            "catches": sum(removed.values()),
        }

    return transaction(_mutate, path)


# --- user config ------------------------------------------------------------
# Small and separate from the pokedex: it is read by the hook on every turn and
# must never risk the collection, and a corrupt or missing file simply means
# "use the defaults" rather than an error.


def load_config(path=CONFIG_PATH):
    """Read config. Never raises; a bad file reads as empty."""
    try:
        with open(path) as f:
            c = json.load(f)
            return c if isinstance(c, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def save_config(fields, path=CONFIG_PATH):
    """Merge `fields` into the config. Returns True on success.

    Written under the pokedex lock so two sessions changing settings at once
    cannot clobber each other with a whole-file write.
    """
    fd = _acquire()
    if fd is None:
        return False
    try:
        cfg = load_config(path)
        cfg.update(fields)
        _write_atomic(path, cfg)
        return True
    except (IOError, OSError):
        return False
    finally:
        _release(fd)


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
    """Overwrite the whole state file. Prefer update_session_state: a bare
    whole-file write is last-writer-wins across processes."""
    try:
        _write_atomic(path, state)
        return True
    except (IOError, OSError):
        return False


def update_session_state(session_key, fields, path=STATE_PATH):
    """Merge `fields` into one session's state under the pokedex lock.

    load-modify-write on a shared file is not made safe by an atomic rename:
    rename only prevents a torn file, not two processes each writing a whole
    file from a stale read. Without the lock, two sessions ending at the same
    moment clobber each other's committed offset, and the loser re-gambles its
    entire transcript on the next turn. Taking the lock (the same one the
    pokedex uses) serialises the read-modify-write.

    Returns True on success, False if the lock was unavailable -- in which case
    nothing was written and the caller must not treat the tokens as spent.
    """
    fd = _acquire()
    if fd is None:
        return False
    try:
        state = load_state(path)
        sess = state.get(session_key) or {}
        sess.update(fields)
        state[session_key] = sess
        # Bound growth: state accumulates one entry per session forever, and a
        # heavy user would otherwise carry thousands of dead sessions.
        if len(state) > MAX_SESSIONS:
            ordered = sorted(
                state.items(), key=lambda kv: kv[1].get("offset", 0), reverse=True
            )
            state = dict(ordered[:MAX_SESSIONS])
            state[session_key] = sess
        _write_atomic(path, state)
        return True
    except (IOError, OSError):
        return False
    finally:
        _release(fd)
