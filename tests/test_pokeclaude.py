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
META = os.path.join(REPO, "plugin", "assets", "pokemon.json")

# Derived from the shipped assets, not hardcoded. The roster grew from 386 to
# 1025 once and will grow again; a literal here turns every roster change into a
# batch of unrelated test failures that say nothing about what actually broke.
with open(META) as _f:
    ROSTER = sorted(int(k) for k in json.load(_f))
ROSTER_SIZE = len(ROSTER)

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


def assistant(uuid, tokens, msg_id=None, **extra):
    d = {
        "type": "assistant",
        "uuid": uuid,
        "message": {"id": msg_id or ("msg_" + uuid), "usage": {"output_tokens": tokens}},
    }
    d.update(extra)
    return d


def prompt(uuid, text="hello"):
    """A real user prompt: what opens a turn."""
    return {"type": "user", "uuid": uuid, "message": {"role": "user", "content": text}}


def tool_result(uuid):
    """A tool result. Recorded as type=user but must NOT open a new turn."""
    return {
        "type": "user",
        "uuid": uuid,
        "toolUseResult": {"ok": True},
        "message": {"role": "user", "content": "result"},
    }


def tool_result_block(uuid):
    """A tool result expressed as a content block rather than toolUseResult."""
    return {
        "type": "user",
        "uuid": uuid,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}],
        },
    }


def blocks(msg_id, tokens, n):
    """One logical assistant message written as n content-block records.

    Claude Code repeats the message's FINAL output_tokens on every record, so a
    correct reader must count `tokens` once, not n times.
    """
    return [assistant("%s-b%d" % (msg_id, i), tokens, msg_id=msg_id) for i in range(n)]


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
            "    r=store.record_catch((int(sys.argv[1])*7+i)%%%d+1, session_id='w'+sys.argv[1])\n"
            "    ok,skip=(ok+1,skip) if r is not None else (ok,skip+1)\n"
            "print(ok,skip)\n"
            % (os.path.join(REPO, "plugin", "lib"), home, ROSTER_SIZE)
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
    # Calibration is now expressed per session rather than per minute: replaying
    # a real 589k-token session should yield roughly one catch on the default.
    ref_tokens = 589_000
    exp = ref_tokens / float(E.TOKENS_PER_CATCH)
    check(0.7 <= exp <= 1.4, "default gives ~1 catch per reference session (%.2f)" % exp)
    check(0 < E.MAX_TURN_PROBABILITY <= 0.5, "single-turn probability is bounded")
    check(
        E.PRESETS["light"] < E.PRESETS["normal"] < E.PRESETS["strict"],
        "presets are ordered light < normal < strict",
    )
    check(
        E.TOKENS_PER_CATCH == E.PRESETS[E.DEFAULT_PRESET],
        "module default matches the default preset",
    )


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
    check(
        len(ids) == ROSTER_SIZE,
        "all %d sprites present (found %d)" % (ROSTER_SIZE, len(ids)),
    )
    check(ids == ROSTER, "sprite ids match the metadata roster exactly")
    check(all(json.load(open(os.path.join(SPRITES, "%d.json" % p)))["w"] == 64
              for p in ids[:20]), "sprites are baked at 64px")
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


def test_hook_turn_scoping():
    """The roll must see ONE turn: the user's prompt to the end of the response.

    Earlier versions tracked a byte offset, which meant the first sight of a
    transcript banked the entire session into one roll -- on a long session that
    read ~188k tokens and hit the 50% cap, 18x a normal turn.
    """
    print("\n[hook] roll is scoped to the last turn only")
    home, _ = fresh_home()
    # The reader moved out of the hook into pokeclaude.transcript when multi-host
    # support landed: Claude Code and Codex share the same JSONL format, so one
    # reader serves both rather than each host's hook carrying a copy.
    from pokeclaude import transcript as m

    # Three turns; only the last one may be counted.
    recs = []
    recs += [prompt("p1")] + blocks("m1", 1000, 2)
    recs += [prompt("p2")] + blocks("m2", 2000, 3)
    recs += [prompt("p3")] + blocks("m3", 3000, 2)
    t = write_transcript(os.path.join(home, "t.jsonl"), recs)

    tok, turn = m.read_turn_tokens(t)
    check(tok == 3000, "only the last turn's tokens count (got %d, want 3000)" % tok)
    check(turn == "p3", "turn marker identifies the opening prompt")

    # Tool results are also type=user; they must NOT split the turn.
    recs = [prompt("q1")] + blocks("a1", 500, 2) + [tool_result("tr1")] + blocks("a2", 700, 2)
    t2 = write_transcript(os.path.join(home, "t2.jsonl"), recs)
    tok2, turn2 = m.read_turn_tokens(t2)
    check(tok2 == 1200, "tool results do not split a turn (got %d, want 1200)" % tok2)
    check(turn2 == "q1", "turn still attributed to the real prompt")

    # A tool_result expressed as a content block must also not split.
    recs = [prompt("r1")] + blocks("b1", 400, 1) + [tool_result_block("trb")] + blocks("b2", 600, 1)
    t3 = write_transcript(os.path.join(home, "t3.jsonl"), recs)
    tok3, _ = m.read_turn_tokens(t3)
    check(tok3 == 1000, "tool_result content block does not split a turn (got %d)" % tok3)

    # Content-block replication within a turn is still collapsed per message.
    t4 = write_transcript(os.path.join(home, "t4.jsonl"), [prompt("s1")] + blocks("one", 884, 4))
    tok4, _ = m.read_turn_tokens(t4)
    check(tok4 == 884, "4 block records of one message count 884 once (got %d)" % tok4)

    # No user prompt at all -> nothing to roll for.
    t5 = write_transcript(os.path.join(home, "t5.jsonl"), blocks("orphan", 900, 2))
    tok5, turn5 = m.read_turn_tokens(t5)
    check(turn5 is None and tok5 == 0, "transcript with no prompt yields no turn")

    # Unreadable transcript degrades quietly.
    tok6, turn6 = m.read_turn_tokens(os.path.join(home, "nope.jsonl"))
    check(tok6 == 0 and turn6 is None, "missing transcript returns no turn")

    # Multibyte content must not break parsing.
    t7 = os.path.join(home, "t7.jsonl")
    with open(t7, "w") as f:
        f.write(json.dumps(prompt("u1", text="✨完全 café 🎮"), ensure_ascii=False) + "\n")
        for r in blocks("mb", 250, 2):
            f.write(json.dumps(r) + "\n")
    tok7, _ = m.read_turn_tokens(t7)
    check(tok7 == 250, "multibyte prompt parses correctly (got %d)" % tok7)


def test_hook_one_roll_per_turn():
    """Stop can fire more than once per turn; only the first may roll."""
    print("\n[hook] one roll per turn")
    home, _ = fresh_home()
    from pokeclaude import store

    # A huge turn so a roll would almost certainly produce output.
    t = write_transcript(
        os.path.join(home, "t.jsonl"), [prompt("p1")] + blocks("m1", 400000, 2)
    )

    outs = []
    for i in range(6):
        rc, out, err = run_hook({"session_id": "s", "transcript_path": t}, home)
        check(rc == 0 and not err, "run %d clean" % (i + 1))
        outs.append(out.strip())

    produced = [o for o in outs if o]
    check(len(produced) <= 1, "at most one roll for one turn (%d rolled)" % len(produced))
    st = store.load_state()
    check(st.get(t, {}).get("last_turn") == "p1", "state records the rolled turn")

    # A NEW prompt is a new turn and becomes eligible again.
    with open(t, "a") as f:
        f.write(json.dumps(prompt("p2")) + "\n")
        for r in blocks("m2", 400000, 2):
            f.write(json.dumps(r) + "\n")
    rc, out, err = run_hook({"session_id": "s", "transcript_path": t}, home)
    check(rc == 0 and not err, "next turn runs clean")
    check(store.load_state().get(t, {}).get("last_turn") == "p2", "new turn is rolled")


def test_state_locking():
    """Regression guard: concurrent sessions must not clobber each other's offset.

    save_state wrote the whole file from a stale read, so two sessions ending at
    once lost one another's committed offset and re-gambled a whole transcript.
    update_session_state serialises that read-modify-write under the lock.
    """
    print("\n[state] concurrent offset commits are not lost")
    home, store = fresh_home()

    worker = os.path.join(home, "sw.py")
    with open(worker, "w") as f:
        f.write(
            "import sys,os\n"
            "sys.path.insert(0,%r)\n"
            "os.environ['POKECLAUDE_HOME']=%r\n"
            "from pokeclaude import store\n"
            "n=sys.argv[1]\n"
            "ok=store.update_session_state('s'+n, {'offset': int(n)*1000, 'last_msg': 'm'+n})\n"
            "print(1 if ok else 0)\n"
            % (os.path.join(REPO, "plugin", "lib"), home)
        )

    n = 12
    procs = [
        subprocess.Popen([sys.executable, worker, str(i)], stdout=subprocess.PIPE)
        for i in range(n)
    ]
    oks = sum(int(p.communicate()[0].decode().strip() or 0) for p in procs)

    st = store.load_state()
    check(oks == n, "all %d concurrent state writes reported success" % n)
    check(len(st) == n, "state.json retains ALL %d sessions (got %d)" % (n, len(st)))
    correct = sum(
        1 for i in range(n) if (st.get("s%d" % i) or {}).get("offset") == i * 1000
    )
    check(correct == n, "every session's offset survived (%d/%d)" % (correct, n))

    # Merging must preserve fields written by an earlier call.
    store.update_session_state("merge", {"offset": 5})
    store.update_session_state("merge", {"last_msg": "abc"})
    mg = store.load_state().get("merge") or {}
    check(mg.get("offset") == 5 and mg.get("last_msg") == "abc", "updates merge, not replace")

    # Growth is bounded so state.json cannot accumulate forever.
    for i in range(store.MAX_SESSIONS + 40):
        store.update_session_state("bulk%d" % i, {"offset": i})
    check(
        len(store.load_state()) <= store.MAX_SESSIONS + 1,
        "session count bounded at MAX_SESSIONS (%d)" % len(store.load_state()),
    )


def test_hook_end_to_end():
    print("\n[hook] end-to-end catch")
    home, _ = fresh_home()
    # A turn needs an opening prompt now that rolls are turn-scoped.
    t = write_transcript(
        os.path.join(home, "t.jsonl"),
        [prompt("p1")] + [assistant("u%d" % i, 200000) for i in range(3)],
    )

    # Tries are sized against the CURRENT cap, not a hardcoded guess: at
    # MAX_TURN_PROBABILITY=0.25 twelve tries flake 3.2% of the time, which made
    # this test intermittently red. Solve for a <1-in-100k dry run instead.
    from pokeclaude import encounter as _E
    import math as _math
    _p = _E.turn_probability(200000)
    tries = int(_math.ceil(_math.log(1e-5) / _math.log(1 - _p)))

    caught, banners = 0, []
    for i in range(tries):
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

    check(caught > 0, "catches fire (%d/%d at p=%.2f)" % (caught, tries, _p))
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
    for pid in ROSTER:
        fstore.record_catch(pid, session_id="full")
    e["POKECLAUDE_HOME"] = full
    e["POKECLAUDE_WIDTH"] = "80"
    p = subprocess.run([sys.executable, POKEDEX, "--stats"], capture_output=True, env=e)
    # Strip escapes before matching: colour codes sit between the two counts, so a
    # raw byte search would miss text that renders correctly.
    stats = visible(p.stdout.decode("utf-8", "replace"))
    check(
        "%d/%d" % (ROSTER_SIZE, ROSTER_SIZE) in stats and "100%" in stats,
        "complete pokedex reports 100%",
    )
    p = subprocess.run([sys.executable, POKEDEX, "--all"], capture_output=True, env=e)
    check(p.returncode == 0, "--all on a complete pokedex renders")


def test_presets_and_config():
    """Difficulty presets, and the config the hook reads them from."""
    print("\n[config] difficulty presets")
    home, store = fresh_home()
    from pokeclaude import encounter as E

    check(E.resolve_preset("strict") == E.PRESETS["strict"], "named preset resolves")
    check(E.resolve_preset("STRICT") == E.PRESETS["strict"], "preset is case-insensitive")
    check(E.resolve_preset(" light ") == E.PRESETS["light"], "surrounding space tolerated")
    for junk in ("nonsense", "", None, 7, {}):
        check(
            E.resolve_preset(junk) == E.PRESETS[E.DEFAULT_PRESET],
            "junk preset %r falls back to the default" % (junk,),
        )

    check(E.configured_tokens_per_catch({}) == E.PRESETS[E.DEFAULT_PRESET], "no config -> default")
    check(
        E.configured_tokens_per_catch({"preset": "light"}) == E.PRESETS["light"],
        "config preset is honoured",
    )
    check(
        E.configured_tokens_per_catch({"tokens_per_catch": 777_000}) == 777_000,
        "numeric override wins over preset",
    )
    check(
        E.configured_tokens_per_catch({"preset": "light", "tokens_per_catch": 0}) == E.PRESETS["light"],
        "a zero override is ignored, not treated as a rate",
    )

    # Round-trip through the real config file.
    check(store.load_config() == {}, "missing config reads as empty")
    check(store.save_config({"preset": "strict"}), "config saves")
    check(store.load_config().get("preset") == "strict", "config persists")
    check(store.save_config({"preset": "light"}), "config updates")
    check(store.load_config().get("preset") == "light", "update took effect")

    with open(store.CONFIG_PATH, "w") as f:
        f.write("{not json")
    check(store.load_config() == {}, "corrupt config reads as empty, no crash")
    check(
        E.configured_tokens_per_catch(store.load_config()) == E.PRESETS[E.DEFAULT_PRESET],
        "corrupt config falls back to the default rate",
    )

    # The rate the presets imply, against the reference session.
    for name, lo, hi in (("light", 1.5, 2.6), ("normal", 0.7, 1.4), ("strict", 0.3, 0.7)):
        exp = 589_000 / float(E.PRESETS[name])
        check(lo <= exp <= hi, "%s ~= %.1f catches per reference session" % (name, exp))


def test_config_cli():
    print("\n[config] CLI")
    home, store = fresh_home()
    script = os.path.join(REPO, "plugin", "scripts", "config.py")

    def run(args):
        e = dict(os.environ)
        e["POKECLAUDE_HOME"] = home
        p = subprocess.run([sys.executable, script] + args, capture_output=True, env=e)
        return p.returncode, visible(p.stdout.decode()), p.stderr.decode()

    rc, out, err = run([])
    check(rc == 0 and not err.strip(), "no-arg run is clean")
    for name in ("light", "normal", "strict"):
        check(name in out, "listing shows %s" % name)
    check("per session" in out, "listing explains the per-session rate")

    rc, out, _ = run(["strict"])
    check(rc == 0 and "strict" in out, "setting a preset reports back")
    check(store.load_config().get("preset") == "strict", "preset written to config")

    rc, out, _ = run(["--tokens", "900000"])
    check(rc == 0, "numeric override accepted")
    check(store.load_config().get("tokens_per_catch") == 900000, "override written")
    check(
        store.load_config().get("preset") is None,
        "choosing a rate clears the preset so it cannot silently win",
    )

    rc, out, _ = run(["strict"])
    check(
        store.load_config().get("tokens_per_catch") is None,
        "choosing a preset clears a previous numeric override",
    )

    rc, out, _ = run(["nonsense"])
    check(rc == 1 and "Unknown preset" in out, "unknown preset exits 1 with a hint")
    rc, out, _ = run(["--tokens", "10"])
    check(rc == 1, "absurdly small rate is rejected")


def test_grayscale():
    print("\n[sprite] uncaught entries render greyscale")
    from pokeclaude import sprite as S
    import json as _json

    blob = _json.load(open(os.path.join(SPRITES, "1.json")))
    gray = S.grayscale(blob)

    check(gray["w"] == blob["w"] and gray["h"] == blob["h"], "dimensions unchanged")
    check(gray["px"] == blob["px"], "pixel indices untouched -- only the palette changes")
    check(len(gray["pal"]) == len(blob["pal"]), "palette length preserved")
    check(
        all(c[0:2] == c[2:4] == c[4:6] for c in gray["pal"]),
        "every palette entry is a true grey (r==g==b)",
    )
    check(
        len({c for c in gray["pal"]}) > 1,
        "shading survives -- not collapsed to one flat tone",
    )
    check(S.render(gray), "greyscale sprite still renders")

    # A flat silhouette would lose the internal structure; luma must not.
    src = {"w": 2, "h": 2, "pal": ["ff0000", "0000ff"], "px": "1212"}
    g = S.grayscale(src, dim=1.0)
    check(g["pal"][0] != g["pal"][1], "red and blue map to different greys, not the same")

    # dim darkens without changing hue-neutrality
    dark = S.grayscale(blob, dim=0.5)
    bright = S.grayscale(blob, dim=1.0)
    check(
        int(dark["pal"][0][0:2], 16) < int(bright["pal"][0][0:2], 16),
        "dim factor darkens the result",
    )

    # The detail view must use it for uncaught species and not for caught ones.
    home, store = fresh_home()
    store.record_catch(1, session_id="g")
    from pokeclaude import dex as D

    meta = _json.load(open(os.path.join(REPO, "plugin", "assets", "pokemon.json")))
    roster = sorted(int(k) for k in meta)

    def greyness(pid, caught):
        b = _json.load(open(os.path.join(SPRITES, "%d.json" % pid)))
        out = "\n".join(D.render_detail(pid, b, meta.get(str(pid)) or {}, caught, roster))
        cols = set(re.findall(r"38;2;(\d+);(\d+);(\d+)", out))
        greys = sum(1 for r, g_, b_ in cols if r == g_ == b_)
        return greys, len(cols)

    g_caught, n_caught = greyness(1, store.load()["caught"].get("1"))
    g_unc, n_unc = greyness(4, None)
    check(g_unc >= n_unc - 3, "uncaught detail view is greyscale (%d/%d grey)" % (g_unc, n_unc))
    check(g_caught < n_caught - 3, "caught detail view stays in colour (%d/%d grey)" % (g_caught, n_caught))


def test_first_line_is_not_art():
    """Both views must open with a TEXT line, never sprite art.

    The hook re-emits output as a systemMessage, and Claude Code prepends
    "PostToolUse:Bash says:" while eating the leading newline -- so whatever sits
    on line 1 ends up beside that label. If that is a row of half-blocks, the top
    of the sprite is visibly shunted sideways.
    """
    print("\n[render] first line is text, not sprite art")
    home, store = fresh_home()
    store.record_catch(1, session_id="h")

    def first_line(args):
        e = dict(os.environ)
        e["POKECLAUDE_HOME"] = home
        e["POKECLAUDE_WIDTH"] = "80"
        p = subprocess.run(
            [sys.executable, POKEDEX] + args, capture_output=True, env=e
        )
        lines = [l for l in visible(p.stdout.decode()).split("\n")]
        # Mimic the harness: drop the leading blank, take what lands beside the label.
        while lines and not lines[0].strip():
            lines.pop(0)
        return lines[0] if lines else ""

    for args in ([], ["--id", "1"], ["--id", "150"], ["--stats"], ["--all"]):
        line = first_line(args)
        blocks = sum(line.count(ch) for ch in "▀▄█")
        check(
            blocks == 0,
            "pokedex %s opens with text, not art (%r)"
            % (" ".join(args) or "(none)", line[:40]),
        )

    # The catch banner is the other hook surface with the same hazard: the Stop
    # hook prepends "Stop says:" to line 1. It opens with the encounter headline,
    # not the sprite's top row, across every species/width/state.
    from pokeclaude import banner

    with open(META) as f:
        meta = json.load(f)
    roster = sorted(int(k) for k in meta)
    banner_bad = []
    for pid in (1, 143, 150, 896, 1025):        # common, wide, legendary, edge, last
        blob = json.load(open(os.path.join(SPRITES, "%d.json" % pid)))
        for width in (60, 80, 120):
            for is_new, dup in ((True, 1), (False, 4)):
                text = banner.compose(
                    blob, meta[str(pid)]["name"], pid, meta[str(pid)]["types"],
                    is_new, dup, 100, len(roster), width=width, roster_ids=roster,
                )
                lines = [l for l in visible(text).split("\n")]
                while lines and not lines[0].strip():
                    lines.pop(0)
                first = lines[0] if lines else ""
                if any(ch in first for ch in "▀▄█"):
                    banner_bad.append((pid, width, is_new, first[:30]))
    check(
        not banner_bad,
        "catch banner opens with text, not art (%s)" % (banner_bad[:3] or "all clean"),
    )
    # And the headline must appear exactly once -- it moved out of the info column
    # into a header, and a botched move would either drop it or duplicate it.
    text = banner.compose(
        json.load(open(os.path.join(SPRITES, "143.json"))), "snorlax", 143,
        ["normal"], True, 1, 1, len(roster), width=80, roster_ids=roster,
    )
    n_title = visible(text).count("appeared!")
    check(n_title == 1, "banner headline appears exactly once (found %d)" % n_title)


def test_rarity_display():
    print("\n[rarity] percentage and tier")
    from pokeclaude import encounter as E
    import json as _json

    meta = _json.load(open(os.path.join(REPO, "plugin", "assets", "pokemon.json")))
    roster = sorted(int(k) for k in meta)

    mew = E.encounter_share(151, roster)
    pidgey = E.encounter_share(16, roster)
    check(0 < mew < pidgey, "a mythical is rarer than a common (%.4f < %.4f)" % (mew, pidgey))
    check(
        abs(sum(E.encounter_share(p, roster) for p in roster) - 100.0) < 0.01,
        "shares sum to 100%",
    )

    check(E.rarity_tier(151) == "MYTHICAL", "Mew is MYTHICAL")
    check(E.rarity_tier(150) == "LEGENDARY", "Mewtwo is LEGENDARY")
    check(E.rarity_tier(25) == "COMMON", "Pikachu is COMMON")

    # Tier must not depend on roster size, or adding a generation would silently
    # reclassify the whole dex.
    check(
        E.rarity_tier(151, roster[:200]) == E.rarity_tier(151, roster),
        "tier is independent of roster size",
    )

    txt = E.format_rarity(151, roster)
    check("%" in txt and "MYTHICAL" in txt, "format_rarity gives percent and tier (%s)" % txt)
    check(E.format_rarity(151, []) == "", "empty roster yields no rarity string")

    tiers = set(E.rarity_tier(p) for p in roster)
    check(tiers <= {"MYTHICAL", "LEGENDARY", "RARE", "COMMON"}, "no unexpected tiers")

    # Gen 4-9 additions. Spot-check one headliner per generation so a bad merge of
    # the rarity bands shows up as a named failure rather than a share drift.
    check(E.rarity_tier(493) == "MYTHICAL", "Arceus is MYTHICAL")
    check(E.rarity_tier(1025) == "MYTHICAL", "Pecharunt (last entry) is MYTHICAL")
    check(E.rarity_tier(483) == "LEGENDARY", "Dialga is LEGENDARY")
    check(E.rarity_tier(1007) == "LEGENDARY", "Koraidon is LEGENDARY")
    check(E.rarity_tier(658) == "COMMON", "Greninja is COMMON")

    # Rayquaza sits on the MYTHICAL/LEGENDARY boundary at weight 0.05; it is
    # flagged legendary, and an inclusive threshold used to mislabel it.
    check(E.rarity_tier(384) == "LEGENDARY", "Rayquaza is LEGENDARY, not MYTHICAL")

    # The bands must partition, not overlap -- an id in two sets would take
    # whichever weight was assigned last, silently.
    overlap = (
        (E.MYTHICAL_IDS & E.APEX_IDS)
        | (E.MYTHICAL_IDS & E.LEGENDARY_IDS)
        | (E.APEX_IDS & E.LEGENDARY_IDS)
    )
    check(not overlap, "rarity bands do not overlap (%s)" % (sorted(overlap) or "none"))
    check(
        set(E.RARITY) == E.MYTHICAL_IDS | E.APEX_IDS | E.LEGENDARY_IDS,
        "RARITY covers exactly the three bands",
    )
    check(
        all(p in roster for p in E.RARITY),
        "every rarity entry is a real roster id",
    )
    check(
        all(0 < w < 1.0 for w in E.RARITY.values()),
        "rare weights are all below the common weight of 1.0",
    )

    # Gen 1-3 odds must not have moved when the roster was extended, or existing
    # collections would silently change difficulty.
    legacy = {
        144: 0.12, 145: 0.12, 146: 0.12, 150: 0.06, 151: 0.04,
        243: 0.12, 244: 0.12, 245: 0.12, 249: 0.06, 250: 0.06, 251: 0.04,
        377: 0.12, 378: 0.12, 379: 0.12, 380: 0.10, 381: 0.10,
        382: 0.06, 383: 0.06, 384: 0.05, 385: 0.04, 386: 0.04,
    }
    drift = {p: (w, E.RARITY.get(p)) for p, w in legacy.items() if E.RARITY.get(p) != w}
    check(not drift, "gen 1-3 rarity weights unchanged (%s)" % (drift or "no drift"))
    check(
        not [p for p in E.RARITY if p <= 386 and p not in legacy],
        "no new gen 1-3 species became rare",
    )


def test_project_scoping():
    print("\n[project] per-project tracking")
    home, store = fresh_home()

    for pid in (25, 25, 25, 1, 133):
        store.record_catch(pid, session_id="a", project="/proj/alpha")
    for pid in (7, 7, 196, 25):
        store.record_catch(pid, session_id="b", project="/proj/beta")

    d = store.load()
    check(len(d["caught"]) == 5, "global collection unions both projects")
    check(d["totals"]["catches"] == 9, "global total counts every catch")

    a, a_catches = store.project_view(d, "/proj/alpha")
    b, b_catches = store.project_view(d, "/proj/beta")
    check(len(a) == 3 and a_catches == 5, "alpha sees only its own 3 species / 5 catches")
    check(len(b) == 3 and b_catches == 4, "beta sees only its own 3 species / 4 catches")
    check(
        a["25"]["count"] == 3 and b["25"]["count"] == 1,
        "per-project counts are independent (pikachu 3 in alpha, 1 in beta)",
    )
    check(d["caught"]["25"]["count"] == 4, "global pikachu count is the sum (4)")

    unknown, n = store.project_view(d, "/proj/never-seen")
    check(unknown == {} and n == 0, "unknown project yields an empty view, no crash")

    # project_key should resolve a git repo root, so subdirs share one Pokedex.
    root = os.path.join(home, "repo")
    os.makedirs(os.path.join(root, ".git"))
    deep = os.path.join(root, "a", "b")
    os.makedirs(deep)
    check(store.project_key(deep) == root, "project_key resolves to the git toplevel")
    plain = os.path.join(home, "plain")
    os.makedirs(plain)
    check(store.project_key(plain) == plain, "non-repo dir is its own project")


def test_release():
    print("\n[release] removing pokemon")
    home, store = fresh_home()

    def seed():
        for pid in (25, 25, 25, 1, 4, 133):
            store.record_catch(pid, session_id="a", project="/proj/alpha")
        for pid in (7, 7, 196):
            store.record_catch(pid, session_id="b", project="/proj/beta")

    seed()
    r = store.release(species_id=25)
    check(r["species"] == 1 and r["catches"] == 3, "releasing one species reports 1 species / 3 catches")
    d = store.load()
    check("25" not in d["caught"], "species is gone from the collection")
    check(d["totals"]["catches"] == 6, "totals decremented by the released count")
    a, _ = store.project_view(d, "/proj/alpha")
    check("25" not in a, "released species also cleared from project records")

    r = store.release(species_id=999)
    check(r["species"] == 0, "releasing something not caught is a no-op")

    # Project-scoped release must not touch the global collection.
    home, store = fresh_home()
    seed()
    before = len(store.load()["caught"])
    r = store.release(species_id=None, project="/proj/beta")
    d = store.load()
    check(r["scope"] == "project" and r["species"] == 2, "project reset clears that project")
    check(len(d["caught"]) == before, "global collection SURVIVES a project reset")
    check("7" in d["caught"] and "196" in d["caught"], "globally caught species remain")
    check("/proj/beta" not in (d.get("projects") or {}), "project record removed")
    a, _ = store.project_view(d, "/proj/alpha")
    check(len(a) == 4, "other projects unaffected")

    # Full global reset.
    home, store = fresh_home()
    seed()
    r = store.release(species_id=None)
    d = store.load()
    check(r["scope"] == "global", "global reset reports global scope")
    check(d["caught"] == {} and d["totals"]["catches"] == 0, "everything cleared")
    check(not (d.get("projects") or {}), "project records cleared too")
    check(store.record_catch(25, session_id="x")["is_new"], "catching works after a full reset")


def test_release_cli():
    print("\n[release] CLI safety gate")
    home, store = fresh_home()
    for pid in (25, 25, 1, 4):
        store.record_catch(pid, session_id="a", project="/proj/alpha")

    script = os.path.join(REPO, "plugin", "scripts", "release.py")

    def run(args):
        e = dict(os.environ)
        e["POKECLAUDE_HOME"] = home
        p = subprocess.run([sys.executable, script] + args, capture_output=True, env=e)
        return p.returncode, visible(p.stdout.decode()), p.stderr.decode()

    rc, out, err = run(["pikachu"])
    check(rc == 2, "dry run exits 2 (nothing changed)")
    check("Would release" in out and "--confirm" in out, "dry run explains what would happen")
    check("25" in store.load()["caught"], "dry run did NOT delete anything")

    rc, out, _ = run(["notapokemon"])
    check(rc == 1 and "Unknown" in out, "unknown name exits 1 with a hint")

    rc, out, _ = run(["mewtwo"])
    check(rc == 0 and "not in" in out, "uncaught species reports nothing to release")

    rc, out, _ = run(["25"])
    check(rc == 2 and "Pikachu" in out, "dex number resolves to the right species")

    rc, out, _ = run(["pikachu", "--confirm"])
    check(rc == 0 and "released" in out.lower(), "--confirm performs the release")
    check("25" not in store.load()["caught"], "species actually removed")

    rc, out, _ = run(["all", "--confirm"])
    check(rc == 0, "release all succeeds")
    check(store.load()["caught"] == {}, "pokedex is empty after release all")

    rc, out, _ = run(["all", "--confirm"])
    check(rc == 0 and "already empty" in out, "releasing an empty pokedex is graceful")


def test_dupes_and_project_cli():
    print("\n[pokedex] duplicates and --project views")
    home, store = fresh_home()
    for pid in (25, 25, 25, 25, 1, 133, 133):
        store.record_catch(pid, session_id="a", project="/proj/alpha")
    for pid in (7, 7, 196):
        store.record_catch(pid, session_id="b", project="/proj/beta")

    def run(args, width="80"):
        e = dict(os.environ)
        e["POKECLAUDE_HOME"] = home
        e["POKECLAUDE_WIDTH"] = width
        p = subprocess.run([sys.executable, POKEDEX] + args, capture_output=True, env=e)
        return p.returncode, visible(p.stdout.decode()), p.stderr.decode()

    rc, out, err = run(["--stats"])
    check(rc == 0 and not err.strip(), "--stats runs clean")
    check("duplicates" in out and "4" in out, "duplicate section lists counts")
    check("pikachu" in out, "most-duplicated species is named")

    rc, out, _ = run(["--dupes"])
    check(rc == 0 and "pikachu" in out and "eevee" in out, "--dupes lists all duplicates")

    rc, out, _ = run(["--project", "--cwd", "/proj/alpha", "--stats"])
    check(rc == 0 and "alpha" in out, "project view is labelled with the project")
    check("3/%d" % ROSTER_SIZE in out, "alpha reports its own 3 species")

    rc, out, _ = run(["--project", "--cwd", "/proj/beta", "--stats"])
    check("2/%d" % ROSTER_SIZE in out, "beta reports its own 2 species")

    rc, out, _ = run(["--project", "--cwd", "/proj/nothing-here", "--stats"])
    check(
        rc == 0 and "0/%d" % ROSTER_SIZE in out,
        "empty project view renders without crashing",
    )

    for args in (["--project", "--cwd", "/proj/alpha"], ["--project", "--all", "--cwd", "/proj/alpha"]):
        rc, out, err = run(args)
        check(rc == 0 and not err.strip(), "pokedex %s renders" % " ".join(args))
        w = max(len(l) for l in out.split("\n")) if out else 0
        check(w <= 80, "project grid fits 80 cols (%d)" % w)


def test_banner_fits():
    """The catch banner must never wrap, for any species at any terminal width.

    Wrapping is not cosmetic here: a wrapped line splits a row of half-block
    glyphs and the sprite becomes unreadable. The guard that prevents it used a
    hardcoded info-column width of 34, which predated the rarity line -- so a
    wide sprite plus a long rarity string ("0.013% of encounters  LEGENDARY")
    overflowed 80 columns. Sweeping the whole roster is what caught it; a
    handful of sample species did not.
    """
    print("\n[banner] catch banner fits every terminal width")
    from pokeclaude import banner

    with open(META) as f:
        meta = json.load(f)

    widths = (40, 60, 80, 100, 120)
    over, errors = [], []
    for pid in ROSTER:
        with open(os.path.join(SPRITES, "%d.json" % pid)) as f:
            blob = json.load(f)
        info = meta[str(pid)]
        for width in widths:
            # Both states matter: the duplicate line and the NEW line differ in
            # length, so one can fit where the other does not.
            for is_new, dup in ((True, 1), (False, 12)):
                try:
                    txt = banner.compose(
                        blob, info["name"], pid, info["types"], is_new, dup,
                        400, len(ROSTER), width=width, roster_ids=ROSTER,
                    )
                except Exception as e:
                    errors.append((pid, width, repr(e)))
                    continue
                widest = max(len(visible(l)) for l in txt.split("\n"))
                if widest > width:
                    over.append((pid, width, widest))

    check(not errors, "every banner composes (%d errors)" % len(errors))
    for e in errors[:3]:
        print("     ", e)
    check(
        not over,
        "no banner exceeds its terminal width (%d overflows, e.g. %s)"
        % (len(over), over[:3] or "none"),
    )

    # The sprite must actually survive: a banner that fits by dropping the art
    # entirely would pass the width check above.
    blob = json.load(open(os.path.join(SPRITES, "896.json")))
    txt = banner.compose(
        blob, "glastrier", 896, ["ice"], True, 1, 400, len(ROSTER),
        width=80, roster_ids=ROSTER,
    )
    check(
        any("▀" in l or "▄" in l for l in txt.split("\n")),
        "banner still contains sprite art at 80 cols",
    )
    check("LEGENDARY" in visible(txt), "banner shows the rarity tier")


def test_shiny():
    """Shiny variants: rate, additive bookkeeping, art, and display."""
    print("\n[shiny] alternate-coloured variants")
    from pokeclaude import encounter as E, sprite as S, banner

    check(
        abs(E.SHINY_CHANCE - 1.0 / 64) < 1e-9,
        "shiny chance is 1 in 64 (got 1 in %.1f)" % (1 / E.SHINY_CHANCE),
    )

    # Rate, measured rather than assumed. 60k rolls keeps the band tight enough
    # to catch an order-of-magnitude error without being flaky.
    hits = sum(E.roll_shiny(seed=E.stable_seed("shiny", i)) for i in range(60000))
    observed = 60000.0 / hits if hits else 0
    check(
        55 < observed < 75,
        "observed shiny rate is near 1 in 64 (got 1 in %.1f)" % observed,
    )

    # Shininess must be independent of species, or rarity would compound and a
    # shiny legendary would be unreachable.
    src = open(os.path.join(REPO, "plugin", "lib", "pokeclaude", "encounter.py")).read()
    sig = src.split("def roll_shiny", 1)[1].split(")", 1)[0]
    check("species" not in sig, "roll_shiny does not depend on species")

    # Every shiny sprite exists, decodes, renders and is actually recoloured.
    shiny_dir = os.path.join(SPRITES, "shiny")
    check(os.path.isdir(shiny_dir), "shiny sprite directory exists")
    shiny_ids = sorted(
        int(f[:-5]) for f in os.listdir(shiny_dir) if f.endswith(".json")
    )
    check(shiny_ids == ROSTER, "a shiny sprite exists for every species")

    bad, identical = [], []
    for pid in shiny_ids:
        try:
            s = S.load(SPRITES, pid, shiny=True)
            n = S.load(SPRITES, pid, shiny=False)
            if not S.render(s):
                bad.append((pid, "renders empty"))
            if not S.render(S.downscale(s, 2)):
                bad.append((pid, "downscale empty"))
            if s["pal"] == n["pal"]:
                identical.append(pid)
        except Exception as e:
            bad.append((pid, repr(e)[:40]))
    check(not bad, "every shiny sprite renders (%s)" % (bad[:3] or "all fine"))
    # Minior (#774) genuinely shares its palette upstream; anything more than a
    # handful would mean the shiny tree was not actually fetched.
    check(
        len(identical) <= 2,
        "shiny art is recoloured, not a copy (%d identical: %s)"
        % (len(identical), identical[:5]),
    )

    # The loader prefers shiny but degrades to normal rather than failing, since a
    # missing variant should cost colours, not the catch.
    check(
        S.load(SPRITES, 25, shiny=True)["pal"] != S.load(SPRITES, 25)["pal"],
        "loader returns shiny art when asked",
    )
    check(S.load(SPRITES, 10 ** 9, shiny=True) is None, "loader returns None if absent")

    # Bookkeeping is additive: a normal and a shiny of one species are both true.
    home, store = fresh_home()
    store.record_catch(25, session_id="a")
    r2 = store.record_catch(25, session_id="b", shiny=True)
    r3 = store.record_catch(25, session_id="c", shiny=True)
    check(r2["is_new_shiny"] and not r3["is_new_shiny"], "first shiny is flagged once")
    entry = store.load()["caught"]["25"]
    check(entry["count"] == 3, "shiny catches still count toward the species total")
    check(entry.get("shiny") == 2, "shiny catches are counted separately")
    check(entry.get("shiny_first"), "first-shiny timestamp is recorded")
    check(store.load()["totals"].get("shinies") == 2, "global shiny total tracked")

    # A pre-shiny Pokedex must keep working untouched -- absent keys mean zero.
    legacy, lstore = fresh_home()
    lstore.record_catch(7, session_id="old")
    old = lstore.load()["caught"]["7"]
    check("shiny" not in old, "a normal catch adds no shiny key")

    # Banner: headline names it, and SHINY appears alongside NEW rather than
    # replacing it, because the two facts are independent.
    with open(META) as f:
        meta = json.load(f)
    blob = S.load(SPRITES, 25, shiny=True)
    text = visible(
        banner.compose(
            blob, "pikachu", 25, ["electric"], True, 1, 1, len(ROSTER),
            width=80, roster_ids=ROSTER, shiny=True,
        )
    )
    check("SHINY PIKACHU" in text, "shiny banner names it in the headline")
    check("1 in 64" in text, "shiny banner states the odds")
    check("NEW" in text, "shiny banner still reports NEW independently")
    plain = visible(
        banner.compose(
            S.load(SPRITES, 25), "pikachu", 25, ["electric"], True, 1, 1,
            len(ROSTER), width=80, roster_ids=ROSTER, shiny=False,
        )
    )
    check("SHINY" not in plain, "a normal catch says nothing about shiny")

    # A shiny duplicate keeps the gold treatment: still a 1-in-64 event.
    dup = visible(
        banner.compose(
            blob, "pikachu", 25, ["electric"], False, 4, 1, len(ROSTER),
            width=80, roster_ids=ROSTER, shiny=True,
        )
    )
    check(
        "SHINY" in dup and "duplicate" in dup,
        "a shiny duplicate reports both facts",
    )

    # --- CLI semantics -----------------------------------------------------
    # Shiny colours are EARNED. --shiny filters the collection; it must never
    # preview colours for a species you have not caught shiny, or the reward is
    # spent before it is won. --normal is the way back for a species you own both
    # of.
    cli, cstore = fresh_home()
    for p in (1, 4, 7, 25):
        cstore.record_catch(p, session_id="s")
    cstore.record_catch(25, session_id="s", shiny=True)   # owns normal AND shiny
    cstore.record_catch(133, session_id="s", shiny=True)  # shiny-only species

    def run_dex(args):
        e = dict(os.environ)
        e["POKECLAUDE_HOME"] = cli
        e["POKECLAUDE_WIDTH"] = "90"
        p = subprocess.run(
            [sys.executable, POKEDEX] + args, capture_output=True, env=e
        )
        return p.returncode, p.stdout.decode("utf-8", "replace")

    rc, out = run_dex(["--shiny"])
    vis = visible(out)
    check(rc == 0, "--shiny exits cleanly")
    check("shinies only" in vis, "--shiny labels the view as a shiny showcase")
    check("pikachu" in vis and "eevee" in vis, "--shiny lists the shiny species")
    check(
        "bulbasaur" not in vis and "squirtle" not in vis,
        "--shiny excludes species with no shiny",
    )

    # The art must actually change with the toggle, and must NOT change for a
    # species whose shiny is not owned.
    _, shiny_view = run_dex(["--id", "25", "--scale", "3"])
    _, normal_view = run_dex(["--id", "25", "--normal", "--scale", "3"])
    check(
        shiny_view != normal_view,
        "--normal renders different art than the shiny default",
    )
    check(
        "showing" in visible(shiny_view) and "--normal" in visible(shiny_view),
        "the detail view says which variant is shown and how to switch",
    )

    _, plain_a = run_dex(["--id", "7", "--scale", "3"])
    _, plain_b = run_dex(["--id", "7", "--shiny", "--scale", "3"])
    check(
        plain_a == plain_b,
        "--shiny does not reveal unearned shiny colours for --id",
    )

    # An empty shiny collection has to say so rather than render an empty grid.
    empty, estore = fresh_home()
    estore.record_catch(1, session_id="s")
    e2 = dict(os.environ)
    e2["POKECLAUDE_HOME"] = empty
    e2["POKECLAUDE_WIDTH"] = "90"
    p = subprocess.run(
        [sys.executable, POKEDEX, "--shiny"], capture_output=True, env=e2
    )
    check(
        p.returncode == 0 and "No shinies yet" in visible(p.stdout.decode()),
        "--shiny with no shinies explains rather than showing an empty grid",
    )

    # Shiny facts must survive the per-project reduction, or --project --shiny
    # would silently return nothing.
    proj, pstore = fresh_home()
    pstore.record_catch(25, session_id="s", project="/proj/x", shiny=True)
    view, _n = pstore.project_view(pstore.load(), "/proj/x")
    check(
        view.get("25", {}).get("shiny") == 1,
        "project_view keeps shiny counts",
    )


def test_hosts():
    """Host adapters: detection, display channel, and token sources."""
    print("\n[hosts] multi-host adapters")
    import io

    from pokeclaude import hosts

    for env, want in (
        ({"POKECLAUDE_HOST": "kiro"}, "kiro"),
        ({"POKECLAUDE_HOST": "KIRO"}, "kiro"),
        ({"CODEX_HOME": "/x"}, "codex"),
        ({"KIRO_IDE": "1"}, "kiro"),
        ({"CURSOR_TRACE_ID": "abc"}, "cursor"),
        ({"COPILOT_HOME": "/x"}, "copilot"),
        ({"CLAUDECODE": "1"}, "claude"),
        ({}, "claude"),
        ({"POKECLAUDE_HOST": "nonsense"}, "claude"),
    ):
        got = hosts.detect(env)
        check(got == want, "detect(%s) -> %s" % (json.dumps(env)[:34], got))

    # An explicit setting must beat env sniffing, or a user cannot correct a
    # wrong guess.
    check(
        hosts.detect({"POKECLAUDE_HOST": "codex", "KIRO_IDE": "1"}) == "codex",
        "explicit POKECLAUDE_HOST overrides detection",
    )

    # Display channel: stdout JSON for hosts that render it, stderr otherwise.
    # The two must never both fire, or a catch would print twice.
    for host in sorted(hosts.HOSTS):
        out, err = io.StringIO(), io.StringIO()
        channel = hosts.emit("BANNER", host, out=out, err=err)
        so, se = out.getvalue(), err.getvalue()
        if channel == "systemMessage":
            payload = json.loads(so)
            ok = payload.get("systemMessage") == "BANNER" and not se
        else:
            ok = channel == "stderr" and "BANNER" in se and not so
        check(ok, "%s emits via %s only" % (host, channel))

    check(
        all(hosts.can_display(h) for h in hosts.HOSTS),
        "every host has some display channel",
    )

    # Token sources.
    cases = [
        ({"usage": {"output_tokens": 5000}, "turn_id": "t1"}, (5000, "t1")),
        ({"usage": {"outputTokens": 700}, "session_id": "s"}, (700, "s")),
        ({"tokens": {"output": 1234}, "message_id": "m"}, (1234, "m")),
        ({"output_tokens": 99, "session_id": "s"}, (99, "s")),
    ]
    for payload, want in cases:
        got = hosts.read_turn_tokens(payload, "cursor")
        check(got == want, "inline usage %s -> %s" % (json.dumps(payload)[:34], got))

    # No usage at all: a flat assumed turn, so the host is playable but never
    # luckier than an instrumented one.
    tokens, marker = hosts.read_turn_tokens({"session_id": "s"}, "copilot")
    check(
        tokens == hosts.BLIND_TURN_TOKENS and marker == "s",
        "a host with no token data falls back to a flat turn",
    )
    check(
        hosts.BLIND_TURN_TOKENS < 5907,
        "the blind fallback is below the measured median turn",
    )
    # Nothing to key on at all means no roll -- otherwise a hook firing twice for
    # one turn would roll twice.
    check(
        hosts.read_turn_tokens({}, "copilot") == (0, None),
        "no identifiable turn means no roll",
    )

    # A transcript is used whenever offered, even by a host whose entry says
    # otherwise: real counts always beat the fallback.
    home, _ = fresh_home()
    recs = [prompt("p1")] + blocks("m1", 4321, 3)
    path = write_transcript(os.path.join(home, "t.jsonl"), recs)
    tokens, marker = hosts.read_turn_tokens({"transcript_path": path}, "kiro")
    check(
        tokens == 4321 and marker == "p1",
        "a transcript is read even for a payload-declared host (got %s)" % tokens,
    )


def test_mono_render():
    """Density-based art for hosts that strip ANSI colour.

    Kiro renders a command's output with escapes removed but glyphs intact, which
    turns a normal render into a flat field of identical blocks -- every pixel
    became the same white rectangle, because the shape lived in the colours.
    """
    print("\n[mono] colour-free rendering")
    from pokeclaude import dex, hosts, sprite as S

    check(not hosts.has_colour("kiro"), "kiro is flagged as colour-stripping")
    check(hosts.has_colour("claude"), "claude keeps colour")
    check(hosts.has_colour("codex"), "codex keeps colour")

    blob = S.downscale(json.load(open(os.path.join(SPRITES, "25.json"))), 3)
    mono = S.render_mono(blob)
    check(bool(mono), "render_mono produces output")

    # No escapes at all: the whole point is surviving a host that removes them.
    check(
        not any("\x1b" in row for row in mono),
        "mono output contains no ANSI escapes",
    )
    # Uniform width, or grid cells cannot pad predictably.
    widths = {len(row) for row in mono}
    check(len(widths) == 1, "every mono row is the same width (%s)" % sorted(widths))

    # Shape must survive: more than one distinct glyph, or it is a flat blob.
    glyphs = set("".join(mono)) - {" "}
    check(
        len(glyphs) >= 3,
        "mono uses a range of densities, not one tone (%s)" % sorted(glyphs),
    )
    check(
        glyphs <= set(S.MONO_RAMP),
        "mono only uses the declared ramp (%s)" % sorted(glyphs),
    )

    # A dark sprite must not vanish: every opaque pixel gets a visible glyph.
    dark = S.downscale(json.load(open(os.path.join(SPRITES, "94.json"))), 3)  # gengar
    dark_rows = S.render_mono(dark)
    check(
        any(ch != " " for ch in "".join(dark_rows)),
        "a dark species still renders a silhouette",
    )

    # Per-sprite normalisation: a low-contrast species must still show detail.
    flat = S.downscale(json.load(open(os.path.join(SPRITES, "411.json"))), 3)
    flat_glyphs = set("".join(S.render_mono(flat))) - {" "}
    check(
        len(flat_glyphs) >= 3,
        "a low-contrast species still shows internal detail (%s)" % sorted(flat_glyphs),
    )

    # Grid alignment, which a ragged mono row would break.
    with open(META) as f:
        meta = json.load(f)
    entries = [(p, {"count": 1, "first": 0, "last": 0}) for p in ROSTER[:4]]
    lines = dex.render_grid(
        entries, SPRITES, meta, cols=4, show_uncaught=True, scale=3, mono=True
    )
    grid_widths = {len(visible(l)) for l in lines if l.strip()}
    check(
        len(grid_widths) == 1,
        "mono grid rows are uniform width (%s)" % sorted(grid_widths),
    )

    # The CLI flag and the env override.
    home, store = fresh_home()
    store.record_catch(25, session_id="s")
    e = dict(os.environ)
    e["POKECLAUDE_HOME"] = home
    e["POKECLAUDE_WIDTH"] = "90"

    def art_style(env, extra=()):
        """Which renderer drew the sprite: half-blocks mean colour, ramp means mono.

        Checked on the ART rather than on escapes anywhere in the output, because
        the header and labels stay coloured either way -- harmless, since a
        stripping host removes them, and useful on a host that does not.
        """
        got = subprocess.run(
            [sys.executable, POKEDEX, "--id", "25"] + list(extra),
            capture_output=True, env=env,
        ).stdout.decode()
        half = any(g in got for g in "▀▄")
        ramp = any(g in got for g in "░▒▓█")
        return "colour" if half else ("mono" if ramp else "neither")

    e["POKECLAUDE_HOST"] = "kiro"
    check(art_style(e) == "mono", "kiro auto-selects mono art")

    e["POKECLAUDE_MONO"] = "0"
    check(art_style(e) == "colour", "POKECLAUDE_MONO=0 restores colour art")
    del e["POKECLAUDE_MONO"]

    e["POKECLAUDE_HOST"] = "claude"
    check(art_style(e) == "colour", "claude gets colour art")
    check(art_style(e, ["--mono"]) == "mono", "--mono forces density art anywhere")


def test_skills():
    """The SKILL.md bundles that give non-Claude hosts slash commands."""
    print("\n[skills] Agent Skills bundles")
    skills_dir = os.path.join(REPO, "skills")
    check(os.path.isdir(skills_dir), "skills/ exists")

    names = sorted(
        n for n in os.listdir(skills_dir)
        if os.path.isdir(os.path.join(skills_dir, n))
    )
    check(bool(names), "at least one skill is defined (%s)" % ", ".join(names))

    for name in names:
        path = os.path.join(skills_dir, name, "SKILL.md")
        check(os.path.isfile(path), "%s has a SKILL.md" % name)
        with open(path) as f:
            body = f.read()

        # Frontmatter must open the file, or the host will not parse it.
        check(body.startswith("---\n"), "%s opens with frontmatter" % name)
        front = body.split("---", 2)[1] if body.count("---") >= 2 else ""
        declared = ""
        for line in front.split("\n"):
            if line.startswith("name:"):
                declared = line.split(":", 1)[1].strip()
        # Kiro requires name == folder name, lowercase/numbers/hyphens.
        check(declared == name, "%s frontmatter name matches its folder" % name)
        check(
            re.match(r"^[a-z0-9-]{1,64}$", declared or "") is not None,
            "%s name is lowercase/hyphens only" % name,
        )
        desc = ""
        for line in front.split("\n"):
            if line.startswith("description:"):
                desc = line.split(":", 1)[1].strip()
        check(bool(desc), "%s has a description" % name)
        check(len(desc) <= 1024, "%s description is within 1024 chars" % name)

        # The command has to locate the repo without depending on a host-set
        # plugin-root variable, since a chat skill gets none.
        check(
            "plugin/scripts/" in body,
            "%s invokes a real script" % name,
        )
        check(
            "POKECLAUDE_ROOT" in body,
            "%s can be pointed at the repo explicitly" % name,
        )

    # Every script a skill references must exist.
    for name in names:
        with open(os.path.join(skills_dir, name, "SKILL.md")) as f:
            body = f.read()
        for rel in re.findall(r"plugin/scripts/([a-z_]+\.py)", body):
            check(
                os.path.isfile(os.path.join(REPO, "plugin", "scripts", rel)),
                "%s references a real script (%s)" % (name, rel),
            )


def test_pokeball_geometry():
    """The generated Pokeball must survive half-block rendering.

    Not cosmetic. The renderer pairs pixel rows into one terminal row each, so a
    1px seam is only ever half a cell and renders as a dashed band, and a 2px seam
    that starts on an odd row straddles two cells and shows as two half-tones.
    Both were shipped and both looked wrong -- the button also sat inside the white
    half instead of on the equator. These assert the geometry that fixes it.
    """
    print("\n[ball] Pokeball geometry survives half-block rendering")
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import animate_demo as ad
    from pokeclaude import sprite as S

    for diameter in (16, 20, 24, 25, 32):
        grid = ad._ball_grid(diameter)
        h, w = len(grid), len(grid[0])
        seam_top = int(diameter / 2.0) + int(diameter / 2.0) % 2

        check(
            seam_top % 2 == 0,
            "d=%d: seam starts on an even row (%d)" % (diameter, seam_top),
        )
        # The seam must be a solid 2px band, and both its rows identical, or it
        # cannot render as one line.
        check(
            grid[seam_top] == grid[seam_top + 1],
            "d=%d: both seam rows are identical" % diameter,
        )
        # Nothing but outline/seam and the button may appear on the seam row.
        body = [ch for ch in grid[seam_top] if ch in "1246"]
        check(not body, "d=%d: seam row carries no body colour" % diameter)

        # The button must straddle the seam symmetrically. Probe a row inside the
        # button rather than a fixed offset: the button scales with the diameter,
        # so a fixed distance falls outside it on small balls.
        def button_span(row_ix):
            if not 0 <= row_ix < h:
                return None
            cols = [i for i, ch in enumerate(grid[row_ix]) if ch == "3"]
            if not cols:
                return None
            # central run only -- the lower hemisphere is white too
            mid = w // 2
            run = [c for c in cols if abs(c - mid) < w // 4]
            return (min(run), max(run)) if run else None

        probe = max(2, int(diameter / 5.6) - 1)
        above = button_span(seam_top - probe)
        below = button_span(seam_top + 1 + probe)
        check(
            above is not None and below is not None and above == below,
            "d=%d: button is symmetric about the seam (%s vs %s, probe=%d)"
            % (diameter, above, below, probe),
        )

        blob = {
            "id": "ball", "w": w, "h": h,
            "pal": list(ad._BALL_PAL),
            "px": "".join(grid),
        }
        check(
            len(blob["px"]) == w * h and S.render(blob),
            "d=%d: renders as a valid sprite" % diameter,
        )

    # Splitting must divide the ball into two equal halves whatever the size.
    for amount in (1, 2, 3):
        opened = ad.ball_blob(open_amount=amount)
        check(
            len(opened["px"]) == opened["w"] * opened["h"],
            "open_amount=%d keeps the grid consistent" % amount,
        )
    closed = ad.ball_blob()
    check(
        ad.ball_blob(open_amount=2)["px"] != closed["px"],
        "opening actually changes the art",
    )
    check(
        ad.ball_blob(shake=1)["px"] != closed["px"],
        "shaking actually changes the art",
    )


def test_readme_svgs():
    """The generated README images must be valid, self-contained and not clip.

    These are the only user-facing artifacts nobody sees fail: a broken SVG still
    renders as *something*, so two real defects shipped before being spotted by
    eye. Both are cheap to assert.
    """
    print("\n[docs] README SVGs are valid and cannot clip")
    import glob
    import xml.etree.ElementTree as ET

    files = sorted(glob.glob(os.path.join(REPO, "docs", "*.svg")))
    check(len(files) >= 4, "README SVGs exist (%d found)" % len(files))

    bad_xml, unpinned, overflow, risky = [], [], [], []
    for path in files:
        name = os.path.basename(path)
        with open(path) as f:
            s = f.read()
        try:
            ET.fromstring(s)
        except ET.ParseError as e:
            bad_xml.append((name, str(e)))
            continue

        # Every text run must pin its width. Cells sit on a fixed grid but glyphs
        # advance at whatever width the viewer's monospace font uses, so an
        # unpinned run overflows the viewport and is clipped mid-word.
        n_text, n_pinned = s.count("<text"), s.count('textLength="')
        if n_text != n_pinned:
            unpinned.append((name, n_pinned, n_text))

        declared = float(re.search(r'width="(\d+)"', s).group(1))
        widest = 0.0
        for m in re.finditer(r'<text x="([\d.]+)"[^>]*textLength="([\d.]+)"', s):
            widest = max(widest, float(m.group(1)) + float(m.group(2)))
        if widest > declared:
            overflow.append((name, widest, declared))

        # GitHub's SVG sanitizer drops these, so an image relying on any of them
        # would render blank or partially in the README.
        found = [
            t for t in ("<script", "<foreignObject", "xlink:href", "<style", "onload")
            if t in s
        ]
        if found:
            risky.append((name, found))

    check(not bad_xml, "every SVG parses as XML (%s)" % (bad_xml[:2] or "all valid"))
    check(not unpinned, "every text run pins textLength (%s)" % (unpinned[:2] or "all pinned"))
    check(not overflow, "no text run exceeds the declared width (%s)" % (overflow[:2] or "none"))
    check(not risky, "no markup GitHub's sanitizer strips (%s)" % (risky[:2] or "none"))

    # Background rects must overlap, not merely tile. Abutting edges land
    # mid-pixel at fractional zoom and antialias into a seam across every row.
    with open(os.path.join(REPO, "docs", "catch-snorlax.svg")) as f:
        s = f.read()
    ys = sorted({
        float(m) for m in re.findall(r'<rect x="[-\d.]+" y="([-\d.]+)"', s)
    })
    heights = {
        float(m) for m in re.findall(r'height="([\d.]+)"', s)
    }
    pitch = [round(b - a, 3) for a, b in zip(ys, ys[1:])]
    row_pitch = min(pitch) if pitch else 0
    check(
        any(h > row_pitch for h in heights if h < 100),
        "background rects overlap their row pitch (no seams at fractional zoom)",
    )

    # Every image the README points at must actually be committed.
    with open(os.path.join(REPO, "README.md")) as f:
        readme = f.read()
    refs = sorted(set(re.findall(r'docs/[A-Za-z0-9._-]+\.svg', readme)))
    missing = [r for r in refs if not os.path.exists(os.path.join(REPO, r))]
    check(refs, "README references SVG images (%d)" % len(refs))
    check(not missing, "every referenced image exists (%s)" % (missing or "all present"))


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
        test_hook_turn_scoping,
        test_hook_one_roll_per_turn,
        test_state_locking,
        test_hook_end_to_end,
        test_pokedex_cli,
        test_presets_and_config,
        test_config_cli,
        test_grayscale,
        test_first_line_is_not_art,
        test_rarity_display,
        test_project_scoping,
        test_release,
        test_release_cli,
        test_dupes_and_project_cli,
        test_banner_fits,
        test_shiny,
        test_hosts,
        test_mono_render,
        test_skills,
        test_pokeball_geometry,
        test_readme_svgs,
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
