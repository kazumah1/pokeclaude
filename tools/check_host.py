#!/usr/bin/env python3
"""Check that PokeClaude works under a given host, without waiting for a catch.

Runs the real hook with a synthetic payload and reports what came back, so a
host-integration problem can be told apart from a plugin problem.

    python3 tools/check_host.py kiro
    python3 tools/check_host.py kiro --show     # print the banner it produced
    python3 tools/check_host.py --all

Uses a throwaway Pokedex, so your real collection is untouched. It forces a catch
by claiming a very large turn, which is why it does not depend on luck.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))

from pokeclaude import hosts as hostlib  # noqa: E402

HOOK = os.path.join(REPO, "plugin", "hooks", "catch.py")
ANSI = re.compile(r"\x1b\[[0-9;]*m")

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def synthetic_transcript(path, tokens):
    """A minimal transcript in the format Claude Code and Codex write."""
    records = [
        {"type": "user", "uuid": "probe-prompt",
         "message": {"role": "user", "content": "probe"}},
        {"type": "assistant", "uuid": "probe-reply",
         "message": {"id": "probe-msg",
                     "usage": {"output_tokens": tokens, "input_tokens": 0}}},
    ]
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


def probe(host, attempts=60, show=False):
    """Fire the hook until it produces a catch, then report the channel used."""
    spec = hostlib.HOSTS[host]
    home = tempfile.mkdtemp(prefix="pokeclaude-check-")
    transcript = synthetic_transcript(os.path.join(home, "t.jsonl"), 900000)

    env = dict(os.environ)
    env["POKECLAUDE_HOME"] = home
    env["POKECLAUDE_HOST"] = host

    for i in range(attempts):
        payload = {
            "session_id": "check-%d" % i,
            "transcript_path": transcript,
            "hook_event_name": spec["event"],
            "cwd": REPO,
        }
        proc = subprocess.run(
            [sys.executable, HOOK],
            input=json.dumps(payload).encode(),
            capture_output=True,
            env=env,
        )
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")

        if proc.returncode != 0:
            return {"ok": False, "why": "hook exited %d: %s" % (proc.returncode, err[:200])}

        if out.strip() or err.strip():
            banner = None
            channel = None
            if out.strip():
                try:
                    banner = json.loads(out)["systemMessage"]
                    channel = "systemMessage (stdout JSON)"
                except (ValueError, KeyError):
                    return {"ok": False, "why": "stdout was not a systemMessage: %s" % out[:200]}
            else:
                banner, channel = err, "stderr"
            return {
                "ok": True,
                "channel": channel,
                "banner": banner,
                "tries": i + 1,
                "colour": bool(re.search(r"\x1b\[38;2;", banner)),
                "art": any(g in banner for g in "▀▄█"),
                "home": home,
            }
        # A miss: clear the per-turn guard so the next attempt rolls again.
        try:
            os.remove(os.path.join(home, "state.json"))
        except OSError:
            pass

    return {"ok": False, "why": "no catch in %d attempts (unexpected)" % attempts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host", nargs="?", help="host key, e.g. kiro")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--show", action="store_true", help="print the banner produced")
    args = ap.parse_args()

    if args.all:
        targets = list(hostlib.HOSTS)
    elif args.host:
        if args.host not in hostlib.HOSTS:
            sys.exit("unknown host %r; known: %s" % (args.host, ", ".join(hostlib.HOSTS)))
        targets = [args.host]
    else:
        targets = [hostlib.detect()]
        print("\n(no host given; probing detected host %r)" % targets[0])

    print()
    failures = 0
    for host in targets:
        spec = hostlib.HOSTS[host]
        result = probe(host, show=args.show)
        if not result["ok"]:
            failures += 1
            print("  %s%-9s FAIL%s  %s" % (RED, host, RESET, result["why"]))
            continue
        print("  %s%-9s ok%s    catch after %d tr%s"
              % (GREEN, host, RESET, result["tries"],
                 "y" if result["tries"] == 1 else "ies"))
        print("      channel  %s" % result["channel"])
        print("      expected %s" % (
            "systemMessage (stdout JSON)" if spec["display"] == "systemMessage"
            else "stderr"))
        print("      colour   %s" % ("yes" if result["colour"] else "NO"))
        print("      art      %s" % ("yes" if result["art"] else "NO"))
        first = ANSI.sub("", result["banner"]).strip().split("\n")[0]
        print("      headline %s" % first[:56])
        if args.show:
            print()
            print(result["banner"])
        print()

    if failures:
        print("%d host(s) failed.\n" % failures)
        return 1
    print(DIM + "The hook works. If a real catch never appears in the host, the")
    print("problem is the host's hook wiring or its handling of that channel," )
    print("not PokeClaude." + RESET)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
