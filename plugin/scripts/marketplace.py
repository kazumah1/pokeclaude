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


def cmd_list(args):
    return mc.create_listing(args.item_id, note=args.note)


def cmd_browse(args):
    return mc.browse()


def cmd_vault(args):
    return mc.vault()


def cmd_offer(args):
    return mc.create_offer(args.listing_id, args.offered_item_id)


def cmd_accept(args):
    return mc.accept_offer(args.offer_id)


def cmd_decline(args):
    return mc.decline_offer(args.offer_id)


def cmd_cancel(args):
    return mc.cancel_listing(args.listing_id)


def cmd_retract(args):
    return mc.withdraw_offer(args.offer_id)


_HANDLERS = {"register": cmd_register, "deposit": cmd_deposit,
             "withdraw": cmd_withdraw, "reconcile": cmd_reconcile,
             "list": cmd_list, "browse": cmd_browse, "vault": cmd_vault,
             "offer": cmd_offer, "accept": cmd_accept, "decline": cmd_decline,
             "cancel": cmd_cancel, "retract": cmd_retract}


def _build_parser():
    p = argparse.ArgumentParser(prog="marketplace")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register"); r.add_argument("name")
    dp = sub.add_parser("deposit"); dp.add_argument("target")
    wp = sub.add_parser("withdraw"); wp.add_argument("item_id", type=int)
    sub.add_parser("reconcile")
    lp = sub.add_parser("list"); lp.add_argument("item_id", type=int); lp.add_argument("--note", default=None)
    sub.add_parser("browse")
    sub.add_parser("vault")
    op = sub.add_parser("offer"); op.add_argument("listing_id", type=int); op.add_argument("offered_item_id", type=int)
    ap = sub.add_parser("accept"); ap.add_argument("offer_id", type=int)
    dp2 = sub.add_parser("decline"); dp2.add_argument("offer_id", type=int)
    cp = sub.add_parser("cancel"); cp.add_argument("listing_id", type=int)
    rp = sub.add_parser("retract"); rp.add_argument("offer_id", type=int)
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
