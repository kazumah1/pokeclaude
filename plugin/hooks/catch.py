#!/usr/bin/env python3
"""Stop hook: roll for a catch once per completed turn.

Reads the turn's real assistant `output_tokens` out of the transcript that
Claude Code points us at, rolls against that, and on success prints a
`systemMessage` containing the sprite banner.

Non-interference is the hard rule here. This runs on every turn the user
completes, so any failure -- unreadable transcript, missing sprite, unavailable
lock -- must exit 0 and print nothing. A dropped catch is invisible; a crashing
or hanging hook breaks someone's session.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
SPRITES = os.path.join(ASSETS, "sprites")
META = os.path.join(ASSETS, "pokemon.json")

# The roll is scoped to a single turn: the tokens the assistant produced between
# the user's prompt and the end of its response. Only the id of the last-rolled
# turn is persisted, which is all that is needed to avoid gambling one prompt
# twice -- and unlike a byte offset it cannot drift, desync on a rewritten
# transcript, or bank a whole session's history into one roll.
STATE_KEY = "last_turn"


def _is_user_prompt(d):
    """Does this record represent the human actually typing something?

    Tool results are also written as `type: "user"`, so they must be excluded --
    otherwise every tool call would look like the start of a new turn and the
    roll would only ever see the tokens after the final tool result.
    """
    if d.get("type") != "user":
        return False
    if d.get("toolUseResult") is not None:
        return False
    content = (d.get("message") or {}).get("content")
    if isinstance(content, list):
        # A tool_result block is a continuation of the same turn, not a prompt.
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return False
    return True


def read_turn_tokens(transcript_path):
    """Tokens the assistant produced for the most recent user prompt.

    Scans back to the last real user prompt and sums the assistant
    `output_tokens` that follow it, which is exactly "from when the user
    prompted to when the agent finished". Returns (tokens, turn_marker), where
    the marker identifies the turn so the same one is never gambled twice.

    One assistant message is written as several records -- one per content block
    (thinking, text, each tool_use) -- and every record repeats the message's
    FINAL output_tokens rather than that block's share. Measured on this
    project's own transcript: 336 records for 173 messages, with all 122
    multi-record messages carrying byte-identical counts, so summing per record
    inflates by 2.32x. Keying on message id collapses them back to one value.
    """
    turn_start = None  # uuid of the prompt that opened the current turn
    seen = {}
    try:
        with open(transcript_path, "rb") as f:
            for raw in f:
                if not raw.endswith(b"\n"):
                    break  # a record still being written
                # Cheap prefilter to skip records that cannot matter. Matches on
                # bare tokens rather than `"type":"user"`, because JSON may or
                # may not carry a space after the colon and a whitespace-
                # sensitive filter would silently drop real prompts.
                if b'"user"' not in raw and b'"usage"' not in raw:
                    continue
                try:
                    d = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if _is_user_prompt(d):
                    turn_start = d.get("uuid") or d.get("timestamp")
                    seen = {}  # a new prompt starts a fresh turn
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message") or {}
                key = msg.get("id") or d.get("uuid")
                if key is None:
                    continue
                # Count input + output, but NOT cache. Prompt caching means the
                # cache figures dwarf real work -- measured over one session:
                # 201M cache_read against 309k output, a 664x ratio -- so
                # including them would make the rate track context size rather
                # than effort. input_tokens is kept for correctness even though
                # caching leaves it tiny (1,976 tokens across 394 messages, a
                # 0.6% addition to output alone).
                usage = msg.get("usage") or {}
                seen[key] = (usage.get("output_tokens") or 0) + (
                    usage.get("input_tokens") or 0
                )
    except (IOError, OSError):
        return 0, None

    if turn_start is None:
        return 0, None
    return sum(seen.values()), turn_start


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

    from pokeclaude import banner, encounter, store

    transcript = payload.get("transcript_path")
    session_id = payload.get("session_id")
    if not transcript:
        return 0

    # Key state on the transcript path, not the session id. A resumed or forked
    # session gets a NEW session_id pointing at a transcript that already holds
    # the previous session's records, so an id-keyed offset would start at 0 and
    # re-gamble the entire history. Sessions with no id would also all collide
    # on the literal key "None" and reset each other. The transcript path is
    # exactly the identity of the token stream being counted.
    skey = str(transcript)
    sess = store.load_state().get(skey) or {}

    tokens, turn = read_turn_tokens(transcript)
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

    try:
        with open(os.path.join(SPRITES, "%d.json" % pid)) as f:
            blob = json.load(f)
    except (IOError, OSError, ValueError):
        return 0

    # Attribute the catch to the project being worked in, so /pokedex --project
    # can report per-project luck. Falls back to the hook's own cwd.
    try:
        project = store.project_key(payload.get("cwd"))
    except Exception:
        project = None

    result = store.record_catch(pid, session_id=session_id, project=project)
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
    )
    print(json.dumps({"systemMessage": msg}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never disturb the session
