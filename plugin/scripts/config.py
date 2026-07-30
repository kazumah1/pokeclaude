#!/usr/bin/env python3
"""Show or change PokeClaude settings.

    config.py                 show current settings
    config.py light           catch roughly twice as often as normal
    config.py normal          the default
    config.py strict          catch roughly half as often as normal
    config.py --tokens 900000 an exact rate, between or beyond the presets

Rates are expressed per turn token (input + output, never cache). The
per-session figures come from replaying a real 589k-token, 147-turn session,
because "1 per N tokens" is easy to misjudge: a session that size makes
"1 per 100k" mean six catches.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from pokeclaude import encounter, store  # noqa: E402

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GOLD = (246, 200, 60)
GREY = (110, 110, 110)

# Expected catches in the reference session, for each preset. Precomputed rather
# than recalculated so this stays a fast, dependency-free display.
SESSION_ESTIMATE = {"light": "~2 catches", "normal": "~1 catch", "strict": "~0.5 catches"}
REFERENCE = "a 589k-token, 147-turn session"


def _rate(tpc):
    """300000 -> '300k', 1200000 -> '1.2M' -- large numbers read badly in k."""
    if tpc >= 1_000_000:
        return ("%.1fM" % (tpc / 1e6)).replace(".0M", "M")
    return "%dk" % (tpc // 1000)


def _c(rgb, text, bold=False):
    return "%s\033[38;2;%d;%d;%dm%s%s" % (
        BOLD if bold else "", rgb[0], rgb[1], rgb[2], text, RESET
    )


def show(cfg):
    active = encounter.configured_tokens_per_catch(cfg)
    override = cfg.get("tokens_per_catch")
    name = cfg.get("preset") or encounter.DEFAULT_PRESET
    name = str(name).strip().lower()
    if name not in encounter.PRESETS:
        name = encounter.DEFAULT_PRESET

    out = ["", "  " + _c(GOLD, "POKECLAUDE", bold=True) + DIM + "  ·  settings" + RESET, ""]

    for key in ("light", "normal", "strict"):
        tpc = encounter.PRESETS[key]
        selected = (not override) and key == name
        mark = _c(GOLD, "▸") if selected else " "
        label = _c(GOLD, "%-7s" % key, bold=True) if selected else DIM + "%-7s" % key + RESET
        out.append(
            "  %s %s %s" % (
                mark, label,
                DIM + "1 per %-6s tokens   %s per session"
                % (_rate(tpc), SESSION_ESTIMATE[key]) + RESET,
            )
        )

    if override:
        out.append("")
        out.append(
            "  " + _c(GOLD, "▸") + " " + _c(GOLD, "custom ", bold=True)
            + DIM + "1 per %s tokens" % _rate(int(override)) + RESET
        )

    out.append("")
    out.append(DIM + "  Reference: %s." % REFERENCE + RESET)
    out.append(DIM + "  Counts turn tokens (input + output). Cache tokens never count." + RESET)
    out.append("")
    out.append(DIM + "  Change with: /pokeclaude:pokeclaude light|normal|strict" + RESET)
    out.append("")
    print("\n".join(out))
    return active


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("preset", nargs="?", default=None)
    ap.add_argument("--tokens", type=int, default=None)
    args = ap.parse_args()

    cfg = store.load_config()

    if args.tokens is not None:
        if args.tokens < 1000:
            print("  Rate must be at least 1000 tokens per catch.")
            return 1
        if not store.save_config({"tokens_per_catch": args.tokens, "preset": None}):
            print(DIM + "  Could not write settings (lock unavailable). Nothing changed." + RESET)
            return 1
        print("")
        print("  Catch rate set to %s." % _c(GOLD, "1 per %s tokens" % _rate(args.tokens), bold=True))
        print("")
        return 0

    if args.preset is None:
        show(cfg)
        return 0

    name = str(args.preset).strip().lower()
    if name not in encounter.PRESETS:
        print("  Unknown preset %r. Choose light, normal or strict." % args.preset)
        return 1

    # Clearing tokens_per_catch matters: a leftover numeric override would
    # silently win over the preset the user just chose.
    if not store.save_config({"preset": name, "tokens_per_catch": None}):
        print(DIM + "  Could not write settings (lock unavailable). Nothing changed." + RESET)
        return 1

    tpc = encounter.PRESETS[name]
    print("")
    print(
        "  Catch rate set to %s %s"
        % (
            _c(GOLD, name, bold=True),
            DIM + "— 1 per %s tokens, %s per session."
            % (_rate(tpc), SESSION_ESTIMATE[name]) + RESET,
        )
    )
    print("")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
