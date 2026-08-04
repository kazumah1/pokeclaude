#!/usr/bin/env python3
"""Check that PokeClaude works under a given host, without waiting for a catch.

Runs the real hook with a synthetic payload and reports what came back, so a
host-integration problem can be told apart from a plugin problem.

    python3 tools/check_host.py kiro
    python3 tools/check_host.py kiro --show     # print the banner it produced
    python3 tools/check_host.py cursor --open   # really open the card in the editor
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

from pokeclaude import card, hosts as hostlib  # noqa: E402

HOOK = os.path.join(REPO, "plugin", "hooks", "catch.py")
ANSI = re.compile(r"\x1b\[[0-9;]*m")

GREEN, RED, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
)


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


def probe(host, attempts=60, show=False, open_image=False):
    """Fire the hook until it produces a catch, then report the channel used."""
    spec = hostlib.HOSTS[host]

    if open_image:
        # A FIXED sandbox, not a fresh one. The card path follows POKECLAUDE_HOME,
        # so a throwaway directory per run would open a new editor tab every time
        # and prove nothing about the thing worth proving: that one tab redraws
        # itself as the file changes. Still not the real Pokedex.
        home = os.path.join(tempfile.gettempdir(), "pokeclaude-check-open")
        if not os.path.isdir(home):
            os.makedirs(home)
    else:
        home = tempfile.mkdtemp(prefix="pokeclaude-check-")
    transcript = synthetic_transcript(os.path.join(home, "t.jsonl"), 900000)

    # The turn marker comes from the transcript and is therefore identical across
    # runs; without this a second run in a reused sandbox reads "already rolled"
    # and never catches anything.
    try:
        os.remove(os.path.join(home, "state.json"))
    except OSError:
        pass

    env = dict(os.environ)
    env["POKECLAUDE_HOME"] = home
    env["POKECLAUDE_HOST"] = host
    # A probe must not open windows unless asked. By default the image card is
    # reported as the command it WOULD run, so checking a host cannot start an
    # editor on someone's machine or steal their focus mid-check.
    env["POKECLAUDE_IMAGE_TAB"] = "1" if open_image else "0"

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
            png = os.path.join(home, "latest-catch.png")
            return {
                "ok": True,
                "channel": channel,
                "banner": banner,
                "tries": i + 1,
                "colour": bool(re.search(r"\x1b\[38;2;", banner)),
                "art": any(g in banner for g in "▀▄█"),
                "home": home,
                "card": png if os.path.exists(png) else None,
            }
        # A miss: clear the per-turn guard so the next attempt rolls again.
        try:
            os.remove(os.path.join(home, "state.json"))
        except OSError:
            pass

    return {"ok": False, "why": "no catch in %d attempts (unexpected)" % attempts}


def _ancestry(limit=6):
    """This process and its parents, as (pid, command) from us upward."""
    chain = []
    pid = os.getpid()
    for _ in range(limit):
        try:
            proc = subprocess.run(
                ["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True
            )
            line = proc.stdout.decode("utf-8", "replace").strip()
            if not line:
                break
            parts = line.split(None, 1)
            ppid = int(parts[0])
            chain.append((pid, os.path.basename(parts[1]) if len(parts) > 1 else "?"))
            if ppid <= 1:
                break
            pid = ppid
        except Exception:
            break
    return chain


def explain():
    """Report what this process sees, without probing or launching anything.

    Meant to be run FROM INSIDE an agent panel, which is the only place the two
    facts that decide everything can be observed: what the environment says we
    are running under, and whether our stdout is a terminal. Both differ between
    a panel and the integrated terminal of the same app, and neither can be
    determined from outside.
    """
    from pokeclaude import card, store

    cfg = store.load_config()
    host = hostlib.detect()
    tty = hostlib.is_terminal(sys.stdout)

    print("")
    print("  detected host   %s   %s" % (host, DIM + hostlib.HOSTS[host]["label"] + RESET))
    print("  stdout is a tty %s   %s" % (
        "YES" if tty else "no",
        DIM + ("a terminal: art stays ANSI" if tty else "a pipe: an image is allowed")
        + RESET,
    ))

    markers = [
        (k, os.environ.get(k)) for k in (
            "POKECLAUDE_HOST", "POKECLAUDE_IMAGE_TAB", "POKECLAUDE_INLINE",
            "CURSOR_TRACE_ID", "KIRO_IDE", "KIRO_WORKSPACE",
            # CODEX_SANDBOX matters as much as CODEX_HOME -- the Codex app sets
            # it and not the other, so omitting it made a correct detection look
            # like it had come from nowhere.
            "CODEX_HOME", "CODEX_SANDBOX", "COPILOT_HOME",
            "CLAUDE_PLUGIN_ROOT", "CLAUDECODE", "TERM_PROGRAM", "TERM",
        )
    ]
    print("")
    print("  environment")
    for k, v in markers:
        print("    %-22s %s" % (k, (v if v else DIM + "unset" + RESET)))

    # Who launched us, up the tree. This is the one thing that cannot be
    # mistaken: run from a shell prompt the parent is a shell, run as an agent's
    # tool call it is the agent's own process. `stdout is a tty` alone cannot
    # tell those apart, because an agent may hand its tool a pty.
    print("")
    print("  launched by")
    chain = _ancestry()
    for depth, (pid, comm) in enumerate(chain):
        print("    %s%-6d %s" % ("  " * depth, pid, comm))
    if not chain:
        # Sandboxed hosts (the Codex app) give `ps` nothing. Only a problem if
        # the environment was silent too, since this is the last resort.
        print("    " + DIM + "unavailable -- this host sandboxes `ps`" + RESET)

    print("")
    print("  config          mono=%r image_tab=%r inline=%r" % (
        cfg.get("mono"), cfg.get("image_tab"), cfg.get("inline")))
    mode = hostlib.image_mode(host, cfg, sys.stdout)
    print("  image mode      %s" % (mode or "none (plain ANSI art)"))

    # Deciding on an image and being ABLE to write one are different questions,
    # and conflating them cost an afternoon: a sandbox that allows reads but not
    # writes looks exactly like a host with no image support, because the card
    # falls back to text without saying why.
    if mode:
        for label, target in (("primary", card.default_path()),
                              ("fallback", card.fallback_path())):
            try:
                d = os.path.dirname(target)
                if not os.path.isdir(d):
                    os.makedirs(d)
                probe = target + ".probe"
                with open(probe, "wb") as f:
                    f.write(b"x")
                os.remove(probe)
                state = "writable"
            except Exception as e:
                state = "NOT writable -- %s" % e.__class__.__name__
            print("  %-15s %s  %s" % (label + " path", target, DIM + state + RESET))
    if mode == "tab":
        argv = card.viewer_argv(card.default_path(), host)
        print("  would run       %s" % (" ".join(argv) if argv else "nothing"))

    # A host that declares NOTHING about markdown images is one where a setting
    # decides. Say so here rather than leaving someone to find it in a doc: this
    # is the exact spot where "it did not work" gets diagnosed.
    if (mode is None and not tty
            and hostlib.HOSTS[host].get("markdown_images") is None
            and not hostlib.viewer(host)
            and (cfg.get("inline") is None)):
        print("")
        print("  " + BOLD + "This host may be able to render an inline image."
              + RESET)
        print(DIM + "  It is opt-in because one adapter serves surfaces that differ:"
              " the app" + RESET)
        print(DIM + "  renders markdown images, the CLI is a terminal and cannot."
              + RESET)
        print("      python3 plugin/scripts/config.py --inline on")
    print("")
    print(DIM + "  If this says the wrong thing, that is the bug: the mode is decided")
    print("  entirely by the two lines at the top." + RESET)
    print("")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host", nargs="?", help="host key, e.g. kiro")
    ap.add_argument(
        "--explain", action="store_true",
        help="report what THIS process detects and would do, and exit. Run it "
             "from inside an agent panel to see what that panel actually looks "
             "like from in here.",
    )
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--show", action="store_true", help="print the banner produced")
    ap.add_argument(
        "--open", action="store_true",
        help="actually open the image card in the host's editor, instead of only "
             "reporting the command. Run it twice: the second catch must redraw "
             "the SAME tab rather than opening another.",
    )
    args = ap.parse_args()

    if args.explain:
        return explain()

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
        result = probe(host, show=args.show, open_image=args.open)
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
        if spec.get("viewer"):
            argv = card.viewer_argv(result.get("card") or card.default_path(), host)
            if args.open:
                print("      image    %s" % (
                    "opened %s (%d bytes)"
                    % (result["card"], os.path.getsize(result["card"]))
                    if result.get("card") else "NO card was written"))
                print("      via      %s" % (" ".join(argv) if argv else "nothing"))
            else:
                print("      image    %s" % (
                    " ".join(argv) if argv
                    else "no viewer found (install the %r shell command)"
                         % spec["viewer"].get("cli")))
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
