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
    # Replay-validated: ~72 min of active work per catch at the current cap.
    # See encounter.py -- the cap and TOKENS_PER_CATCH interact, so this is a
    # sanity band rather than a precise target.
    mins = E.TOKENS_PER_CATCH / 1020.0
    check(40 <= mins <= 90, "calibration is in a sane band (%.0f min)" % mins)
    check(0 < E.MAX_TURN_PROBABILITY <= 0.5, "single-turn probability is bounded")


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
    m = load_hook()

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
    check("3/386" in out, "alpha reports its own 3 species")

    rc, out, _ = run(["--project", "--cwd", "/proj/beta", "--stats"])
    check("2/386" in out, "beta reports its own 2 species")

    rc, out, _ = run(["--project", "--cwd", "/proj/nothing-here", "--stats"])
    check(rc == 0 and "0/386" in out, "empty project view renders without crashing")

    for args in (["--project", "--cwd", "/proj/alpha"], ["--project", "--all", "--cwd", "/proj/alpha"]):
        rc, out, err = run(args)
        check(rc == 0 and not err.strip(), "pokedex %s renders" % " ".join(args))
        w = max(len(l) for l in out.split("\n")) if out else 0
        check(w <= 80, "project grid fits 80 cols (%d)" % w)


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
        test_project_scoping,
        test_release,
        test_release_cli,
        test_dupes_and_project_cli,
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
