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

# Tokens are counted from a byte offset rather than by remembering message ids.
# A bounded id cache cannot work here: any id evicted from the cache is reported
# fresh again on the next turn, so the same tokens get gambled repeatedly and the
# real catch rate drifts far above the calibrated one. An offset is O(1) to store
# and guarantees each transcript line is counted exactly once.
STATE_KEY = "offset"
CARRY_KEY = "last_msg"  # last message id counted, for blocks split across turns


def read_turn_tokens(transcript_path, offset, carry=None):
    """Sum assistant output_tokens written since byte `offset`.

    Returns (tokens, new_offset, last_message_id). Reading forward from a stored
    offset means each line is scanned exactly once and the cost is proportional
    to what the turn actually appended, not to the whole transcript.

    `carry` is the last message id counted by the previous call; it guards the
    case where one message's blocks are split across a turn boundary.

    If the file is shorter than the offset it was replaced or rotated, so we
    restart from the beginning rather than trusting a stale position.
    """
    try:
        size = os.path.getsize(transcript_path)
    except OSError:
        return 0, offset, carry

    if size < offset:  # rotated/truncated: the old position is meaningless
        offset = 0
    if size == offset:  # nothing appended since the last roll
        return 0, offset, carry

    # One assistant message is written as several records -- one per content
    # block (thinking, text, each tool_use) -- and every record repeats the
    # message's FINAL output_tokens rather than that block's share. Summing per
    # record therefore counts a multi-block message 2-3x. Measured on this
    # project's own transcript: 336 records for 173 messages, with all 122
    # multi-record messages carrying byte-identical counts, giving 2.32x
    # inflation. Keying on message id collapses them back to one value each.
    seen = {}
    last_id = None
    try:
        with open(transcript_path, errors="replace") as f:
            if offset:
                f.seek(offset)
            for line in f:
                if not line.endswith("\n"):
                    # A partial trailing line is still being written; leave the
                    # offset before it so it is counted once it is complete.
                    break
                offset += len(line.encode("utf-8", "replace"))
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message") or {}
                tokens = (msg.get("usage") or {}).get("output_tokens") or 0
                # Fall back to the record uuid when there is no message id, so a
                # malformed record still contributes at most once.
                key = msg.get("id") or d.get("uuid") or ("line-%d" % offset)
                seen[key] = tokens  # replicated value: last write wins
                last_id = key
    except (IOError, OSError):
        return 0, offset, carry

    # A message whose blocks straddle a turn boundary appears in this window and
    # the previous one. It was already paid for, so drop it.
    if carry is not None:
        seen.pop(carry, None)

    return sum(seen.values()), offset, (last_id if last_id is not None else carry)


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

    skey = str(session_id)
    sess = store.load_state().get(skey) or {}
    offset = sess.get(STATE_KEY) or 0
    carry = sess.get(CARRY_KEY)

    tokens, new_offset, last_id = read_turn_tokens(transcript, offset, carry)
    if new_offset == offset:  # nothing new to gamble
        return 0

    # Commit before rolling, so a crash mid-roll cannot let the same tokens be
    # gambled twice. The update is done under the same lock as the pokedex,
    # because two sessions ending at once would otherwise clobber each other's
    # offset with a whole-file write and re-gamble an entire transcript.
    store.update_session_state(
        skey, {STATE_KEY: new_offset, CARRY_KEY: last_id}
    )

    if tokens <= 0:
        return 0

    hit, _p = encounter.roll(tokens)
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
    )
    print(json.dumps({"systemMessage": msg}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never disturb the session
