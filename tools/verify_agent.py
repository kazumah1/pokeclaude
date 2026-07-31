#!/usr/bin/env python3
"""Verify PokeClaude on a real agent, and report what is actually proven.

Answers the question the README cannot answer from a docs read: does this agent
INVOKE the hook, and does the banner REACH the user? Those are separate, and both
have to be observed rather than assumed.

    python3 tools/verify_agent.py codex --arm      # 1. arm, then use the agent
    python3 tools/verify_agent.py codex           # 2. read the verdict
    python3 tools/verify_agent.py codex --disarm  # 3. put settings back

Arming raises the catch rate so a catch happens within a few turns instead of one
per session, and turns on a trace log so a hook that fires but misses is
distinguishable from a hook that never ran. Your real Pokedex and catch rate are
saved and restored by --disarm.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))

from pokeclaude import hosts as hostlib  # noqa: E402
from pokeclaude import store  # noqa: E402

TRACE = os.path.expanduser("~/.pokeclaude-verify.jsonl")
BACKUP = os.path.expanduser("~/.pokeclaude-verify-config.bak")

# A catch every ~2k tokens: a few real turns rather than a whole session.
ARMED_RATE = 2000

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
)


def env_line(host):
    """The environment an agent needs so its hook writes a trace."""
    return "POKECLAUDE_TRACE=%s POKECLAUDE_HOST=%s" % (TRACE, host)


def arm(host):
    cfg_path = store.CONFIG_PATH
    if os.path.exists(cfg_path) and not os.path.exists(BACKUP):
        shutil.copy2(cfg_path, BACKUP)
    store.save_config({"tokens_per_catch": ARMED_RATE, "preset": None})

    open(TRACE, "w").close()  # start from empty so the verdict is unambiguous

    spec = hostlib.HOSTS[host]
    print()
    print("  Armed for %s%s%s." % (GREEN, spec["label"], RESET))
    print()
    print("  Catch rate is temporarily 1 per %s tokens, and the hook will log to" % f"{ARMED_RATE:,}")
    print("  %s" % TRACE)
    print()
    print("  Now do this:")
    print()
    print("    1. Make sure the hook is installed for this agent:")
    if host in ("claude", "codex"):
        print("         %s plugin list        # look for pokeclaude" % host)
    else:
        print("         python3 install.py --host %s" % host)
    print()
    print("    2. Export the trace variable where the agent will see it, then")
    print("       start the agent from that same shell:")
    print()
    print("         export POKECLAUDE_TRACE=%s" % TRACE)
    print("         %s" % host)
    print()
    print("       %sIf the agent is a GUI app, launch it from the terminal so it" % DIM)
    print("       inherits the variable -- otherwise the trace stays empty and the")
    print("       result is inconclusive rather than negative.%s" % RESET)
    print()
    print("    3. Have a few real exchanges with it -- anything that makes it work,")
    print("       three or four turns is plenty.")
    print()
    print("    4. Come back and run:")
    print("         python3 tools/verify_agent.py %s" % host)
    print()


def read_trace():
    if not os.path.exists(TRACE):
        return []
    out = []
    with open(TRACE) as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def report(host):
    spec = hostlib.HOSTS[host]
    events = read_trace()
    invoked = [e for e in events if e.get("event") == "invoked"]
    tokens = [e for e in events if e.get("event") == "tokens"]
    rolled = [e for e in events if e.get("event") == "rolled"]
    emitted = [e for e in events if e.get("event") == "emitted"]
    skipped = [e for e in events if e.get("event") == "skipped"]

    def verdict(ok, label, detail=""):
        mark = "%sPASS%s" % (GREEN, RESET) if ok else "%sNOT SEEN%s" % (YELLOW, RESET)
        print("  %-34s %s %s" % (label, mark, detail))

    print()
    print("  %s%s%s -- verification report" % (GREEN, spec["label"], RESET))
    print("  " + "-" * 58)

    if not events:
        print()
        print("  %sNo trace events at all.%s" % (RED, RESET))
        print()
        print("  That means the hook never ran. Either it is not installed for this")
        print("  agent, or the agent did not see POKECLAUDE_TRACE. Check both:")
        print()
        print("    python3 install.py --list")
        print("    echo $POKECLAUDE_TRACE      # inside the shell you launched from")
        print()
        print("  %sThis is inconclusive, not a failure -- an unexported variable looks" % DIM)
        print("  identical to a hook that never fires.%s" % RESET)
        print()
        return 1

    verdict(bool(invoked), "1. Agent invokes the hook",
            "%d time(s)" % len(invoked))

    if invoked:
        keys = invoked[-1].get("keys") or []
        print("       %spayload keys: %s%s" % (DIM, ", ".join(keys[:9]), RESET))
        detected = invoked[-1].get("host")
        if detected != host:
            print("       %s! detected host was %r, not %r -- set POKECLAUDE_HOST%s"
                  % (YELLOW, detected, host, RESET))

    counted = [e for e in tokens if (e.get("tokens") or 0) > 0]
    verdict(bool(counted), "2. Turn tokens are readable",
            "max %s, via %s" % (
                max((e.get("tokens") or 0) for e in tokens) if tokens else 0,
                counted[-1].get("source") if counted else "n/a"))

    verdict(bool(rolled), "3. A roll happens", "%d roll(s)" % len(rolled))
    if rolled:
        hits = [e for e in rolled if e.get("hit")]
        print("       %s%d hit / %d rolls, last p=%s%s"
              % (DIM, len(hits), len(rolled), rolled[-1].get("probability"), RESET))

    verdict(bool(emitted), "4. A banner is emitted",
            "channel: %s" % emitted[-1].get("channel") if emitted else "")

    if skipped:
        why = {}
        for e in skipped:
            why[e.get("why")] = why.get(e.get("why"), 0) + 1
        print()
        print("  %sskips: %s%s" % (DIM, ", ".join(
            "%s (%d)" % (k, v) for k, v in why.items()), RESET))

    print()
    if emitted:
        print("  %sVerified end to end.%s The hook fires, a catch was rolled, and the"
              % (GREEN, RESET))
        print("  banner went out on %r." % emitted[-1].get("channel"))
        print()
        print("  Last thing only you can judge: did you SEE it on screen? The channel")
        print("  above is what we wrote to; whether the agent displays it is its choice.")
    elif rolled:
        print("  %sHook works, no catch yet.%s %d roll(s) all missed. Have a few more"
              % (YELLOW, RESET, len(rolled)))
        print("  turns and re-run -- at 1 per %s tokens this should not take long."
              % f"{ARMED_RATE:,}")
    elif invoked:
        print("  %sHook fires but never rolls.%s The agent invokes it, but no countable"
              % (YELLOW, RESET))
        print("  turn was found. Its payload probably carries no token usage:")
        print("    %s" % json.dumps(invoked[-1].get("keys")))
        print("  That is an adapter gap, not a broken install.")
    print()
    return 0


def disarm():
    if os.path.exists(BACKUP):
        shutil.copy2(BACKUP, store.CONFIG_PATH)
        os.remove(BACKUP)
        print("\n  Catch rate restored from backup.")
    else:
        store.save_config({"tokens_per_catch": None, "preset": "normal"})
        print("\n  Catch rate reset to normal.")
    if os.path.exists(TRACE):
        os.remove(TRACE)
        print("  Trace log removed.")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host", nargs="?", help="agent key: %s" % ", ".join(hostlib.HOSTS))
    ap.add_argument("--arm", action="store_true", help="raise the rate and start tracing")
    ap.add_argument("--disarm", action="store_true", help="restore settings")
    args = ap.parse_args()

    if args.disarm:
        disarm()
        return 0

    if not args.host:
        ap.error("which agent? one of: %s" % ", ".join(hostlib.HOSTS))
    if args.host not in hostlib.HOSTS:
        ap.error("unknown agent %r" % args.host)

    if args.arm:
        arm(args.host)
        return 0
    return report(args.host)


if __name__ == "__main__":
    sys.exit(main())
