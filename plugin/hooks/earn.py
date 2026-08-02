#!/usr/bin/env python3
"""Stop hook: credit the bankroll from the turn's real token usage.

Reads input+output tokens (never cache) for the most recent user prompt from
the transcript — same method as pokeclaude's catch hook — and credits the
bankroll once per turn, keyed on a last_turn marker so a turn is never counted
twice. Any failure exits 0 silently.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))


def _is_user_prompt(d):
    if d.get("type") != "user" or d.get("toolUseResult") is not None:
        return False
    content = (d.get("message") or {}).get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return False
    return True


def read_turn_tokens(transcript_path):
    turn_start = None
    seen = {}
    try:
        with open(transcript_path, "rb") as f:
            for raw in f:
                if not raw.endswith(b"\n"):
                    break
                if b'"user"' not in raw and b'"usage"' not in raw:
                    continue
                try:
                    d = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if _is_user_prompt(d):
                    turn_start = d.get("uuid") or d.get("timestamp")
                    seen = {}
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message") or {}
                key = msg.get("id") or d.get("uuid")
                if key is None:
                    continue
                usage = msg.get("usage") or {}
                seen[key] = (usage.get("output_tokens") or 0) + (usage.get("input_tokens") or 0)
    except (IOError, OSError):
        return 0, None
    if turn_start is None:
        return 0, None
    return sum(seen.values()), turn_start


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    transcript = payload.get("transcript_path")
    if not transcript:
        return 0
    from casino import bankroll, store
    tokens, turn = read_turn_tokens(transcript)
    if turn is None or tokens <= 0:
        return 0
    state = store.load()
    if state.get("last_turn") == turn:
        return 0
    credit = bankroll.credit_amount(tokens, state["config"])

    def mut(s):
        s["last_turn"] = turn
        s["bankroll"] += credit
    store.transaction(mut)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never disturb the session
