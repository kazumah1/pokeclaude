#!/usr/bin/env python3
"""Install PokeClaude's hooks into whichever agent CLIs you have.

    python3 install.py                 # detect installed hosts and wire them up
    python3 install.py --dry-run       # show what would change, write nothing
    python3 install.py --host kiro     # just one host
    python3 install.py --list          # what is detected and already installed
    python3 install.py --uninstall     # remove PokeClaude's hooks again

Existing hook config is merged, not overwritten: your other hooks are left alone
and PokeClaude's entries are tagged so they can be found and removed later.
Everything is backed up to <file>.pokeclaude-backup before the first change.
"""
import argparse
import json
import os
import shutil
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))

from pokeclaude import hosts as hostlib  # noqa: E402

HOOKS_DIR = os.path.join(REPO, "plugin", "hooks")
CATCH = os.path.join(HOOKS_DIR, "catch.py")
SHOW = os.path.join(HOOKS_DIR, "show.py")

# Marks our entries so uninstall can find them without guessing.
TAG = "pokeclaude"
MARKER_KEY = "pokeclaudeManaged"


def _expand(path):
    return os.path.expanduser(path)


def installed_hosts():
    """Which hosts appear to be present on this machine."""
    found = []
    for key, spec in hostlib.HOSTS.items():
        directory = _expand(spec["config_dir"])
        # A host counts as present if its config directory exists, or its binary
        # is on PATH. Either is enough; requiring both misses fresh installs.
        if os.path.isdir(directory) or shutil.which(key):
            found.append(key)
    return found


def hook_command(script):
    """The command a host should run. Quoted, since paths may contain spaces."""
    return 'python3 "%s"' % script


def claude_config(spec):
    """Claude Code: a Stop hook plus the PostToolUse re-emitter for colour."""
    return {
        "hooks": {
            "Stop": [
                {
                    MARKER_KEY: True,
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command(CATCH),
                            "timeout": 5,
                        }
                    ],
                }
            ],
            "PostToolUse": [
                {
                    MARKER_KEY: True,
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command(SHOW),
                            "timeout": 5,
                        }
                    ],
                }
            ],
        }
    }


def generic_config(spec):
    """Codex, Cursor, Copilot: one turn-end hook, event name per host."""
    return {
        "hooks": {
            spec["event"]: [
                {
                    MARKER_KEY: True,
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command(CATCH),
                            "timeout": 5,
                        }
                    ]
                }
            ]
        }
    }


def kiro_config(spec):
    """Kiro uses a flat list of named hooks rather than an event map."""
    return {
        "version": "v1",
        "hooks": [
            {
                MARKER_KEY: True,
                "name": "pokeclaude-catch",
                "description": "Roll for a Pokemon catch when the agent finishes a turn",
                "trigger": spec["event"],
                "action": {"type": "command", "command": hook_command(CATCH)},
                "timeout": 5,
                "enabled": True,
            }
        ],
    }


BUILDERS = {
    "claude": claude_config,
    "codex": generic_config,
    "cursor": generic_config,
    "kiro": kiro_config,
    "copilot": generic_config,
}


def target_path(host):
    spec = hostlib.HOSTS[host]
    return os.path.join(_expand(spec["config_dir"]), spec["hooks_file"])


def is_ours(entry):
    """Is this hook entry one of ours?

    Checked via an explicit marker key rather than by matching the command
    string: the command contains the repo path, which the user is free to rename
    or move, and a path-based check would then fail to clean up.
    """
    if isinstance(entry, dict) and entry.get(MARKER_KEY):
        return True
    return '"%s": true' % MARKER_KEY in json.dumps(entry).replace(" ", "")


def merge(existing, addition, host):
    """Merge our hooks into whatever is already configured.

    Kiro's flat list and everyone else's event map need different handling, but
    both are additive: nothing already present is removed.
    """
    if host == "kiro":
        out = dict(existing) if existing else {"version": "v1", "hooks": []}
        keep = [h for h in (out.get("hooks") or []) if not is_ours(h)]
        out["hooks"] = keep + addition["hooks"]
        return out

    out = dict(existing) if existing else {}
    hooks = dict(out.get("hooks") or {})
    for event, groups in addition["hooks"].items():
        current = [g for g in (hooks.get(event) or []) if not is_ours(g)]
        hooks[event] = current + groups
    out["hooks"] = hooks
    if host == "cursor":
        out.setdefault("version", 1)
    return out


def strip(existing, host):
    """Remove only our entries, leaving the rest of the file intact."""
    if not existing:
        return existing
    if host == "kiro":
        out = dict(existing)
        out["hooks"] = [h for h in (out.get("hooks") or []) if not is_ours(h)]
        return out
    out = dict(existing)
    hooks = {}
    for event, groups in (out.get("hooks") or {}).items():
        kept = [g for g in groups if not is_ours(g)]
        if kept:
            hooks[event] = kept
    out["hooks"] = hooks
    return out


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (IOError, OSError):
        return None
    except ValueError:
        sys.stderr.write("  ! %s is not valid JSON; leaving it alone\n" % path)
        return "INVALID"


def write_json(path, data, dry_run):
    if dry_run:
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        backup = path + ".pokeclaude-backup"
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
    tmp = path + ".pokeclaude-tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return True


def install_one(host, dry_run=False, uninstall=False):
    spec = hostlib.HOSTS[host]
    path = target_path(host)
    existing = read_json(path)
    if existing == "INVALID":
        return False

    if uninstall:
        if not existing:
            print("  %-18s nothing to remove" % spec["label"])
            return True
        merged = strip(existing, host)
    else:
        merged = merge(existing, BUILDERS[host](spec), host)

    write_json(path, merged, dry_run)
    verb = "would remove" if (uninstall and dry_run) else (
        "removed" if uninstall else ("would install" if dry_run else "installed")
    )
    channel = spec["display"]
    note = "" if channel == "systemMessage" else "  (banner via stderr)"
    print("  %-18s %s -> %s%s" % (spec["label"], verb, path, note))
    return True


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--host", action="append", help="install for one host only")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--list", action="store_true", help="show detected hosts")
    ap.add_argument("--all", action="store_true", help="wire every known host")
    args = ap.parse_args()

    if not os.path.exists(CATCH):
        sys.exit("cannot find %s -- run this from the repo root" % CATCH)

    detected = installed_hosts()

    if args.list:
        print("\nKnown hosts:\n")
        for key, spec in hostlib.HOSTS.items():
            path = target_path(key)
            cfg = read_json(path)
            wired = bool(cfg) and TAG in json.dumps(cfg) if cfg != "INVALID" else False
            print(
                "  %-10s %-20s %-9s %s"
                % (
                    key,
                    spec["label"],
                    "present" if key in detected else "-",
                    "installed" if wired else "",
                )
            )
        print()
        return 0

    targets = args.host or (list(hostlib.HOSTS) if args.all else detected)
    unknown = [t for t in targets if t not in hostlib.HOSTS]
    if unknown:
        sys.exit("unknown host(s): %s\nknown: %s"
                 % (", ".join(unknown), ", ".join(hostlib.HOSTS)))

    if not targets:
        print("\nNo supported agent CLIs detected.")
        print("Use --all to wire every known host anyway, or --host <name>.\n")
        return 0

    action = "Uninstalling from" if args.uninstall else "Installing into"
    print("\n%s %d host(s)%s:\n"
          % (action, len(targets), " (dry run)" if args.dry_run else ""))
    ok = True
    for host in targets:
        ok = install_one(host, args.dry_run, args.uninstall) and ok

    print()
    if not args.uninstall and not args.dry_run:
        print("Restart your agent CLI so it picks up the hooks.")
        print("Then run the pokedex script to see your collection:")
        print("  python3 %s\n" % os.path.join(REPO, "plugin", "scripts", "pokedex.py"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
