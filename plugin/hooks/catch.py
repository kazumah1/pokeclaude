#!/usr/bin/env python3
"""Turn-end hook: roll for a catch once per completed turn.

Runs under any supported agent CLI. The host-specific parts -- where the turn's
token count lives and how to show the user a banner -- come from
pokeclaude.hosts; everything else here is shared.

Non-interference is the hard rule. This runs on every turn the user completes, so
any failure (unreadable transcript, missing sprite, unavailable lock) must exit 0
and print nothing. A dropped catch is invisible; a crashing or hanging hook breaks
someone's session.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
SPRITES = os.path.join(ASSETS, "sprites")
META = os.path.join(ASSETS, "pokemon.json")

# Only the id of the last-rolled turn is persisted, which is all that is needed to
# avoid gambling one prompt twice.
STATE_KEY = "last_turn"


def load_roster():
    try:
        with open(META) as f:
            meta = json.load(f)
    except (IOError, OSError, ValueError):
        return {}, []
    ids = sorted(int(k) for k in meta)
    return meta, ids


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0

    if os.environ.get("POKECLAUDE_DISABLE"):
        return 0

    from pokeclaude import banner, encounter, hosts, store

    host = hosts.detect()
    session_id = payload.get("session_id") or payload.get("conversation_id")

    # Key state on the transcript path where a host provides one, not the session
    # id: a resumed or forked session gets a NEW id pointing at a transcript that
    # already holds the previous session's records, so an id-keyed offset would
    # re-gamble the whole history. Hosts without a transcript fall back to the
    # session id, which is coarser but still prevents a double-roll.
    transcript = payload.get("transcript_path") or payload.get("transcriptPath")
    skey = str(transcript or session_id or host)
    sess = store.load_state().get(skey) or {}

    tokens, turn = hosts.read_turn_tokens(payload, host)
    if turn is None or tokens <= 0:
        return 0
    if sess.get(STATE_KEY) == turn:
        # Already rolled for this turn. Stop can fire more than once per turn
        # (e.g. after a subagent finishes), and rolling again would hand out
        # several chances for one prompt.
        return 0

    # Commit before rolling, so a crash mid-roll cannot let the same turn be
    # gambled twice. Written under the same lock as the pokedex, because two
    # sessions ending at once would otherwise clobber each other's record with a
    # whole-file write.
    store.update_session_state(skey, {STATE_KEY: turn})

    # Rate comes from the user's chosen preset (light/normal/strict), falling
    # back to the default if the config is missing or malformed.
    tpc = encounter.configured_tokens_per_catch(store.load_config())
    hit, _p = encounter.roll(tokens, tokens_per_catch=tpc)
    if not hit:
        return 0

    meta, roster = load_roster()
    if not roster:
        return 0

    pid = encounter.pick_species(roster, store.caught_ids())
    if pid is None:
        return 0

    # Rolled independently of the species, so shininess does not compound with
    # rarity -- a shiny legendary stays a genuine one-off rather than the product
    # of two long odds nobody reaches.
    is_shiny = encounter.roll_shiny()

    from pokeclaude import sprite as spritelib

    blob = spritelib.load(SPRITES, pid, shiny=is_shiny)
    if blob is None:
        return 0
    # If the shiny art is missing the loader falls back to the normal sprite; do
    # not then claim the catch was shiny, or the banner would announce colours it
    # is not showing.
    if is_shiny and not os.path.exists(
        os.path.join(SPRITES, "shiny", "%d.json" % pid)
    ):
        is_shiny = False

    # Attribute the catch to the project being worked in, so /pokedex --project
    # can report per-project luck. Falls back to the hook's own cwd.
    try:
        project = store.project_key(payload.get("cwd"))
    except Exception:
        project = None

    result = store.record_catch(
        pid, session_id=session_id, project=project, shiny=is_shiny
    )
    if result is None:  # lock unavailable -- stay silent rather than lie
        return 0

    info = meta.get(str(pid)) or {}
    msg = banner.compose(
        blob,
        name=info.get("name", "pokemon"),
        dex_id=pid,
        type_names=info.get("types") or [],
        is_new=result["is_new"],
        dup_count=result["count"],
        unique=result["unique"],
        roster_size=len(roster),
        roster_ids=roster,
        shiny=is_shiny,
    )

    # The host decides the channel. Where none can display, the catch is still
    # recorded and marked unseen so the Pokedex can announce it later.
    channel = hosts.emit(msg, host)
    if channel != "systemMessage":
        store.mark_unseen(pid)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never disturb the session
