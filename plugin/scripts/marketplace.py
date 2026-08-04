#!/usr/bin/env python3
"""Pokémon marketplace CLI. Inert unless POKECLAUDE_MARKET_URL (or config) is set.

    marketplace register <name>
    (deposit/withdraw/list/browse/vault/offer/accept/decline/cancel added in later tasks)
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from pokeclaude import marketplace_client as mc  # noqa: E402


def cmd_register(args):
    return mc.register(args.name)


def cmd_deposit(args):
    return mc.deposit(args.target)


def cmd_withdraw(args):
    return mc.withdraw(args.item_id)


def cmd_reconcile(args):
    return mc.reconcile()


_HANDLERS = {"register": cmd_register, "deposit": cmd_deposit,
             "withdraw": cmd_withdraw, "reconcile": cmd_reconcile}


def _build_parser():
    p = argparse.ArgumentParser(prog="marketplace")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register"); r.add_argument("name")
    dp = sub.add_parser("deposit"); dp.add_argument("target")
    wp = sub.add_parser("withdraw"); wp.add_argument("item_id", type=int)
    sub.add_parser("reconcile")
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
    except Exception as e:
        print(json.dumps({"error": "internal: %s" % e}))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
