#!/usr/bin/env python3
"""PokeClaude test suite. Runs without pytest: `python3 tests/test_pokeclaude.py`.

Every test isolates state via POKECLAUDE_HOME so the user's real Pokedex at
~/.claude/pokeclaude/ is never touched. That isolation is asserted, not assumed --
a test suite that silently writes to a real collection would be worse than no
tests at all.
"""
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))

HOOK = os.path.join(REPO, "plugin", "hooks", "catch.py")
POKEDEX = os.path.join(REPO, "plugin", "scripts", "pokedex.py")
SPRITES = os.path.join(REPO, "plugin", "assets", "sprites")

ANSI = re.compile(r"\x1b\[[0-9;]*m")
FAILURES = []
PASSED = []


def visible(line):
    return ANSI.sub("", line)


def check(cond, label):
    (PASSED if cond else FAILURES).append(label)
    print("  %s %s" % ("ok  " if cond else "FAIL", label))
    return cond


def fresh_home():
    """A private POKECLAUDE_HOME, with the store re-imported to pick it up."""
    d = tempfile.mkdtemp(prefix="pokeclaude-test-")
    os.environ["POKECLAUDE_HOME"] = d
    import pokeclaude.store as store

    importlib.reload(store)
    assert store.ROOT == d, "store did not honour POKECLAUDE_HOME (%s)" % store.ROOT
    assert ".claude/pokeclaude" not in store.ROOT, "REFUSING: would touch real pokedex"
    return d, store


def load_hook():
    spec = importlib.util.spec_from_file_location("catchmod", HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_hook(payload, home, env=None):
    e = dict(os.environ)
    e["POKECLAUDE_HOME"] = home
    if env:
        e.update(env)
    body = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run(
        [sys.executable, HOOK], input=body.encode(), capture_output=True, env=e
    )
    return p.returncode, p.stdout.decode(), p.stderr.decode()


def write_transcript(path, records):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


def assistant(uuid, tokens, **extra):
    d = {"type": "assistant", "uuid": uuid, "message": {"usage": {"output_tokens": tokens}}}
    d.update(extra)
    return d


# --------------------------------------------------------------------------
def test_store_basics():
    print("\n[store] basics")
    home, store = fresh_home()

    r = store.record_catch(25, session_id="s1")
    check(r["is_new"] is True and r["count"] == 1, "first catch is new, count=1")

    r = store.record_catch(25, session_id="s1")
    check(r["is_new"] is False and r["count"] == 2, "second catch is duplicate, count=2")

    r = store.record_catch(133, session_id="s1")
    check(r["unique"] == 2, "unique count tracks distinct species")
    check(store.caught_ids() == {25, 133}, "caught_ids returns the right set")

    d = store.load()
    check(d["totals"]["catches"] == 3, "totals.catches counts every catch")
    check(
        not [f for f in os.listdir(home) if f.startswith(".tmp-")],
        "no temp files left behind",
    )
    check(not os.path.exists(store.LOCK_PATH), "lock released after write")


def test_store_corruption():
    print("\n[store] corruption is quarantined, not clobbered")
    home, store = fresh_home()
    with open(store.DEX_PATH, "w") as f:
        f.write('{"caught":{"25":{"cou')  # truncated mid-write

    d = store.load()
    check(d["caught"] == {}, "corrupt file reads as empty")
    q = [f for f in os.listdir(home) if "corrupt" in f]
    check(bool(q), "corrupt file quarantined to .corrupt-*")
    if q:
        check(
            open(os.path.join(home, q[0])).read() == '{"caught":{"25":{"cou',
            "quarantined bytes preserved for recovery",
        )
    check(store.record_catch(25, session_id="s") is not None, "writes work after corruption")


def test_store_stale_lock():
    print("\n[store] stale lock is broken")
    home, store = fresh_home()
    os.makedirs(home, exist_ok=True)
    with open(store.LOCK_PATH, "w") as f:
        f.write("99999")
    old = time.time() - (store.LOCK_STALE_S + 10)
    os.utime(store.LOCK_PATH, (old, old))

    r = store.record_catch(7, session_id="s")
    check(r is not None and r["is_new"], "write succeeds despite a stale lock")


def test_store_concurrency():
    print("\n[store] concurrent writers lose nothing")
    home, store = fresh_home()
    worker = os.path.join(home, "w.py")
    with open(worker, "w") as f:
        f.write(
            "import sys,os\n"
            "sys.path.insert(0,%r)\n"
            "os.environ['POKECLAUDE_HOME']=%r\n"
            "from pokeclaude import store\n"
            "ok=skip=0\n"
            "for i in range(6):\n"
            "    r=store.record_catch((int(sys.argv[1])*7+i)%%386+1, session_id='w'+sys.argv[1])\n"
            "    ok,skip=(ok+1,skip) if r is not None else (ok,skip+1)\n"
            "print(ok,skip)\n"
            % (os.path.join(REPO, "plugin", "lib"), home)
        )

    n = 14
    procs = [
        subprocess.Popen([sys.executable, worker, str(i)], stdout=subprocess.PIPE)
        for i in range(n)
    ]
    out = [p.communicate()[0].decode().split() for p in procs]
    ok = sum(int(o[0]) for o in out if len(o) == 2)
    skip = sum(int(o[1]) for o in out if len(o) == 2)

    check(ok + skip == n * 6, "every attempt accounted for (%d+%d==%d)" % (ok, skip, n * 6))
    try:
        d = json.load(open(store.DEX_PATH))
        check(True, "pokedex is still valid JSON after %d concurrent writers" % n)
        check(d["totals"]["catches"] == ok, "totals match recorded writes, none lost")
        check(
            sum(v["count"] for v in d["caught"].values()) == ok,
            "per-species counts sum to recorded writes",
        )
    except ValueError:
        check(False, "pokedex is still valid JSON")
    check(
        not [f for f in os.listdir(home) if f.startswith(".tmp-")],
        "no temp files left after concurrent writes",
    )


# --------------------------------------------------------------------------
def test_encounter_probability():
    print("\n[encounter] probability model")
    from pokeclaude import encounter as E

    check(E.turn_probability(0) == 0.0, "zero tokens -> zero chance")
    check(E.turn_probability(-5) == 0.0, "negative tokens -> zero chance")
    ps = [E.turn_probability(t) for t in (1000, 5000, 20000, 60000)]
    check(ps == sorted(ps), "probability rises with tokens")
    check(
        E.turn_probability(10 ** 9) <= E.MAX_TURN_PROBABILITY,
        "capped at MAX_TURN_PROBABILITY even for absurd input",
    )
    mins = E.TOKENS_PER_CATCH / 3310.0
    check(45 <= mins <= 60, "calibration lands in the 45-60 min target (%.0f min)" % mins)


def test_encounter_selection():
    print("\n[encounter] species selection")
    from pokeclaude import encounter as E

    roster = list(range(1, 387))
    check(E.pick_species([], set()) is None, "empty roster -> None")
    check(all(E.pick_species(roster, set()) in roster for _ in range(200)), "always in roster")

    full = set(roster)
    picks = [E.pick_species(roster, full) for _ in range(200)]
    check(all(p in roster for p in picks), "full dex still yields valid picks (never dries up)")

    a = E.pick_species(roster, set(), seed=E.stable_seed("x"))
    b = E.pick_species(roster, set(), seed=E.stable_seed("x"))
    check(a == b, "stable_seed makes selection reproducible")

    # Duplicates possible but rarer than new, per the user's requirement.
    caught = set(range(1, 194))  # half the roster
    n = 30000
    dups = sum(
        1
        for i in range(n)
        if E.pick_species(roster, caught, seed=E.stable_seed("d", i)) in caught
    )
    rate = dups / float(n)
    check(rate > 0.01, "duplicates DO happen (%.1f%%)" % (100 * rate))
    check(rate < 0.5, "duplicates rarer than new (%.1f%% < 50%%)" % (100 * rate))

    # Per-species: an uncaught species should be ~1/DUPLICATE_WEIGHT more likely
    # than a caught one of equal rarity.
    from collections import Counter

    c = Counter(
        E.pick_species(roster, caught, seed=E.stable_seed("p", i)) for i in range(60000)
    )
    new_hits = sum(c[i] for i in range(194, 387) if i not in E.RARITY)
    dup_hits = sum(c[i] for i in range(1, 194) if i not in E.RARITY)
    ratio = new_hits / float(dup_hits or 1)
    expected = 1.0 / E.DUPLICATE_WEIGHT
    check(
        expected * 0.6 < ratio < expected * 1.6,
        "new/dup selection ratio ~%.1fx (got %.1fx)" % (expected, ratio),
    )

    legend = Counter(
        E.pick_species(roster, set(), seed=E.stable_seed("r", i)) for i in range(60000)
    )
    check(
        legend[150] < legend[16],
        "Mewtwo rarer than Pidgey (%d vs %d)" % (legend[150], legend[16]),
    )


# --------------------------------------------------------------------------
def test_sprite():
    print("\n[sprite] codec and renderer")
    from pokeclaude import sprite as S

    blob = {"w": 2, "h": 2, "pal": ["ff0000"], "px": "1111"}
    pal, rows = S.decode(blob)
    check(pal[0] is None, "palette index 0 is transparent")
    check(pal[1] == (255, 0, 0), "palette decodes hex to rgb")
    check(len(rows) == 2 and len(rows[0]) == 2, "grid shape round-trips")
    check(len(S.render(blob)) == 1, "2 pixel rows -> 1 terminal row")

    odd = {"w": 2, "h": 3, "pal": ["ff0000"], "px": "111111"}
    check(len(S.render(odd)) == 2, "odd height pads to whole rows")

    check(S.render({"w": 2, "h": 2, "pal": [], "px": "0000"}) == [], "all-transparent -> no rows")
    check(len(S.render({"w": 1, "h": 1, "pal": ["ffffff"], "px": "1"})) == 1, "1x1 renders")

    try:
        S.decode({"w": 4, "h": 4, "pal": ["ffffff"], "px": "11"})
        check(False, "malformed px length raises ValueError")
    except ValueError:
        check(True, "malformed px length raises ValueError")

    check(S.visible_width(blob) <= blob["w"], "visible_width never exceeds w")

    # Every real baked sprite must render, and stay recognizable when downscaled.
    ids = sorted(int(f[:-5]) for f in os.listdir(SPRITES) if f.endswith(".json"))
    bad, vanished, wide = [], [], []
    for pid in ids:
        b = json.load(open(os.path.join(SPRITES, "%d.json" % pid)))
        try:
            rows = S.render(b)
            if not rows:
                bad.append(pid)
            if len(rows) != (b["h"] + 1) // 2:
                bad.append(pid)
            for r in rows:
                if len(visible(r)) > b["w"]:
                    wide.append(pid)
                    break
            half = S.downscale(b, 2)
            if not S.render(half):
                vanished.append(pid)
        except Exception:
            bad.append(pid)
    check(len(ids) == 386, "all 386 sprites present")
    check(not bad, "every sprite renders correctly (%d bad)" % len(bad))
    check(not wide, "no sprite renders wider than its pixel width")
    check(not vanished, "no sprite vanishes when downscaled 2x (%s)" % (vanished[:5] or "none"))


# --------------------------------------------------------------------------
def test_hook_noninterference():
    print("\n[hook] non-interference (must ALWAYS exit 0, silent on failure)")
    home, _ = fresh_home()
    cases = [
        ("malformed stdin", "not json{{{"),
        ("empty stdin", ""),
        ("json but not an object", "[1,2,3]"),
        ("no transcript_path", {"session_id": "x"}),
        ("nonexistent transcript", {"session_id": "x", "transcript_path": "/nope/x.jsonl"}),
        ("transcript is a directory", {"session_id": "x", "transcript_path": home}),
        ("session_id missing", {"transcript_path": "/nope/x.jsonl"}),
        ("session_id is null", {"session_id": None, "transcript_path": "/nope/x.jsonl"}),
    ]
    for label, payload in cases:
        rc, out, err = run_hook(payload, home)
        check(rc == 0 and out == "" and err == "", "%s -> exit 0, no output" % label)

    t = write_transcript(os.path.join(home, "t.jsonl"), [assistant("u1", 10 ** 6)])
    rc, out, err = run_hook(
        {"session_id": "d", "transcript_path": t}, home, {"POKECLAUDE_DISABLE": "1"}
    )
    check(rc == 0 and out == "", "POKECLAUDE_DISABLE=1 suppresses everything")


def test_hook_no_double_spend():
    print("\n[hook] token accounting is single-spend")
    home, _ = fresh_home()
    m = load_hook()

    # The exact shape of the bug that was found and fixed: many small records.
    recs = [assistant("u%04d" % i, 100) for i in range(600)]
    t = write_transcript(os.path.join(home, "t.jsonl"), recs)

    tok1, off1 = m.read_turn_tokens(t, 0)
    check(tok1 == 60000, "first read counts every token (%d)" % tok1)
    tok2, off2 = m.read_turn_tokens(t, off1)
    check(tok2 == 0, "re-reading an unchanged transcript counts 0 (regression guard)")
    check(off2 == off1, "offset does not move when nothing was appended")

    with open(t, "a") as f:
        for i in range(3):
            f.write(json.dumps(assistant("n%d" % i, 500)) + "\n")
    tok3, _ = m.read_turn_tokens(t, off2)
    check(tok3 == 1500, "only newly appended tokens are counted (%d)" % tok3)

    # /clear and /compact can shrink or replace the transcript.
    small = write_transcript(os.path.join(home, "s.jsonl"), [assistant("r1", 42)])
    tok4, _ = m.read_turn_tokens(small, 999999)
    check(tok4 == 42, "offset past EOF restarts cleanly (rotation/compact)")

    # A line still being written must not be counted twice.
    p = os.path.join(home, "part.jsonl")
    with open(p, "w") as f:
        f.write(json.dumps(assistant("p1", 10)) + "\n")
        f.write('{"type":"assistant","uuid":"p2","message":{"usa')
    tok5, off5 = m.read_turn_tokens(p, 0)
    check(tok5 == 10, "partial trailing line is skipped")
    with open(p, "a") as f:
        f.write('ge":{"output_tokens":77}}}\n')
    tok6, _ = m.read_turn_tokens(p, off5)
    check(tok6 == 77, "completed line counted exactly once")

    # Multi-byte content must not desync the byte offset.
    u = os.path.join(home, "uni.jsonl")
    write_transcript(u, [assistant("完全な絵文字✨", 5), assistant("u2", 9)])
    tok7, off7 = m.read_turn_tokens(u, 0)
    check(tok7 == 14, "multi-byte transcript counts correctly")
    check(off7 == os.path.getsize(u), "offset matches byte size exactly (no drift)")


def test_hook_end_to_end():
    print("\n[hook] end-to-end catch")
    home, _ = fresh_home()
    t = write_transcript(os.path.join(home, "t.jsonl"), [assistant("u%d" % i, 200000) for i in range(3)])

    caught, banners = 0, []
    for i in range(12):  # p=0.5 per fresh session; 12 tries makes a dry run ~0.02%
        h = tempfile.mkdtemp(prefix="pokeclaude-e2e-")
        rc, out, err = run_hook({"session_id": "e%d" % i, "transcript_path": t}, h)
        if rc != 0 or err:
            check(False, "hook exited cleanly (rc=%d err=%s)" % (rc, err[:80]))
            return
        if out.strip():
            try:
                msg = json.loads(out)["systemMessage"]
            except (ValueError, KeyError):
                check(False, "catch output is valid JSON with systemMessage")
                return
            caught += 1
            banners.append(msg)

    check(caught > 0, "catches fire (%d/12 at p=0.5)" % caught)
    if banners:
        b = banners[0]
        w = max(len(visible(l)) for l in b.split("\n"))
        check(w <= 80, "banner fits 80 columns (%d)" % w)
        check("A wild" in visible(b), "banner announces the encounter")
        check("\x1b[38;2;" in b, "banner carries truecolor escapes")
        check("▀" in b or "▄" in b, "banner contains half-block pixel art")


# --------------------------------------------------------------------------
def test_pokedex_cli():
    print("\n[pokedex] CLI robustness")
    home, store = fresh_home()
    for pid in (1, 4, 7, 25, 94, 133, 143, 150):
        store.record_catch(pid, session_id="cli")
    store.record_catch(25, session_id="cli")

    def run(args, extra_env=None):
        e = dict(os.environ)
        e["POKECLAUDE_HOME"] = home
        e["POKECLAUDE_WIDTH"] = "80"
        if extra_env:
            e.update(extra_env)
        p = subprocess.run(
            [sys.executable, POKEDEX] + args, capture_output=True, env=e
        )
        return p.returncode, p.stdout.decode(), p.stderr.decode()

    argsets = [
        [], ["--all"], ["--stats"], ["--scale", "1"], ["--id", "25"],
        ["--page", "0"], ["--page", "-3"], ["--page", "99999"],
        ["--per-page", "0"], ["--cols", "0"], ["--scale", "0"],
        ["--width", "1"], ["--width", "20"], ["--id", "-1"],
    ]
    for a in argsets:
        rc, out, err = run(a)
        ok = rc == 0 and not err.strip()
        if not ok and a == ["--id", "-1"]:
            ok = rc == 1 and not err.strip()  # documented "no sprite" path
        check(ok, "pokedex %s -> clean (rc=%d%s)" % (" ".join(a) or "(none)", rc, " err" if err.strip() else ""))

    rc, out, _ = run([])
    w = max(len(visible(l)) for l in out.split("\n")) if out else 0
    check(w <= 80, "default view fits 80 columns (%d)" % w)

    for width in (40, 60, 80, 100, 120, 200):
        rc, out, _ = run([], {"POKECLAUDE_WIDTH": str(width)})
        mw = max(len(visible(l)) for l in out.split("\n")) if out else 0
        check(mw <= width, "width=%d respected (rendered %d)" % (width, mw))

    empty, _ = fresh_home()
    e = dict(os.environ)
    e["POKECLAUDE_HOME"] = empty
    p = subprocess.run([sys.executable, POKEDEX], capture_output=True, env=e)
    check(p.returncode == 0 and b"No Pokemon caught yet" in p.stdout, "empty pokedex renders a hint")

    full, fstore = fresh_home()
    for pid in range(1, 387):
        fstore.record_catch(pid, session_id="full")
    e["POKECLAUDE_HOME"] = full
    e["POKECLAUDE_WIDTH"] = "80"
    p = subprocess.run([sys.executable, POKEDEX, "--stats"], capture_output=True, env=e)
    # Strip escapes before matching: colour codes sit between "386" and "/386",
    # so a raw byte search would miss text that renders correctly.
    stats = visible(p.stdout.decode("utf-8", "replace"))
    check("386/386" in stats and "100%" in stats, "complete pokedex reports 100%")
    p = subprocess.run([sys.executable, POKEDEX, "--all"], capture_output=True, env=e)
    check(p.returncode == 0, "--all on a complete pokedex renders")


def main():
    print("PokeClaude test suite (python %s)" % sys.version.split()[0])
    real = os.path.join(os.path.expanduser("~"), ".claude", "pokeclaude")
    before = os.path.exists(real)

    for fn in (
        test_store_basics,
        test_store_corruption,
        test_store_stale_lock,
        test_store_concurrency,
        test_encounter_probability,
        test_encounter_selection,
        test_sprite,
        test_hook_noninterference,
        test_hook_no_double_spend,
        test_hook_end_to_end,
        test_pokedex_cli,
    ):
        try:
            fn()
        except Exception as e:
            import traceback

            FAILURES.append("%s raised %s" % (fn.__name__, e))
            print("  FAIL %s raised:\n%s" % (fn.__name__, traceback.format_exc()))

    # The suite must never have created or mutated the real collection.
    if not before:
        check(not os.path.exists(real), "real pokedex was never created by the tests")

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILURES)))
    for f in FAILURES:
        print("  FAILED: %s" % f)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
