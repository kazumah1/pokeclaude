#!/usr/bin/env python3
"""Pokemon trading CLI — gift a Pokemon to a code, claim a code into your Pokedex.

    trade.py gift pikachu          -> prints a POKETRADE-<code> (your copy leaves the dex)
    trade.py claim POKETRADE-<..>  -> adds the Pokemon to your Pokedex

Prints exactly one JSON object; the collection is only ever touched through
pokeclaude's own locked store.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from pokeclaude import trade  # noqa: E402


def cmd_gift(args):
    return trade.gift_species(args.target)


def cmd_claim(args):
    return trade.claim_trade(args.code)


_HANDLERS = {"gift": cmd_gift, "claim": cmd_claim}


def _build_parser():
    p = argparse.ArgumentParser(prog="trade")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gift"); g.add_argument("target")
    c = sub.add_parser("claim"); c.add_argument("code")
    return p


def dispatch(argv):
    args = _build_parser().parse_args(argv)
    return _HANDLERS[args.cmd](args)


def main(argv):
    try:
        print(json.dumps(dispatch(argv)))
        return 0
    except SystemExit:
        raise
    except Exception as e:  # never crash without a JSON reply
        print(json.dumps({"error": "internal: %s" % e}))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
