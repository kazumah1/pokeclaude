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

# Only count tokens produced after the previous roll, so resumed or compacted
# sessions cannot re-bank tokens that were already gambled.
STATE_KEY = "counted_uuids"
MAX_TRACKED_UUIDS = 400


# Only the tail of a transcript can contain messages we have not already
# counted, and transcripts grow past 10MB in long sessions. Reading just the
# tail keeps this hook flat-cost instead of getting slower all session.
TAIL_BYTES = 512 * 1024


def read_turn_tokens(transcript_path, seen):
    """Sum assistant output_tokens for messages not yet counted.

    Returns (tokens, newly_seen_uuids). Only the last TAIL_BYTES are examined:
    anything older has necessarily been seen by a previous turn's roll. The
    first (possibly truncated) line of the window is discarded.
    """
    total, fresh = 0, []
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, errors="replace") as f:
            if size > TAIL_BYTES:
                f.seek(size - TAIL_BYTES)
                f.readline()  # discard the partial line we landed mid-way into
            for line in f:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                uuid = d.get("uuid") or d.get("requestId")
                if not uuid or uuid in seen:
                    continue
                usage = (d.get("message") or {}).get("usage") or {}
                total += usage.get("output_tokens") or 0
                fresh.append(uuid)
    except (IOError, OSError):
        return 0, []
    return total, fresh


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

    state = store.load_state()
    sess = state.get(str(session_id)) or {}
    seen = set(sess.get(STATE_KEY) or [])

    tokens, fresh = read_turn_tokens(transcript, seen)
    if not fresh:
        return 0

    # Record the tokens as spent before deciding, so a crash mid-roll cannot let
    # the same tokens be gambled twice.
    merged = (sess.get(STATE_KEY) or []) + fresh
    sess[STATE_KEY] = merged[-MAX_TRACKED_UUIDS:]
    state[str(session_id)] = sess
    store.save_state(state)

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

    result = store.record_catch(pid, session_id=session_id)
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
