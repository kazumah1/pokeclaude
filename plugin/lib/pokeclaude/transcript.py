"""Read a turn's token usage out of a JSONL transcript.

Claude Code and Codex both write one JSON record per line and point hooks at the
file, so one reader serves both.

Two traps, each of which produced a wrong number here first:

  * One assistant message becomes SEVERAL records -- one per content block
    (thinking, text, each tool_use) -- and every one repeats the message's final
    `output_tokens` rather than that block's share. Measured on this project's own
    transcript: 336 records for 173 messages, all 122 multi-record messages
    carrying identical counts, so summing per record inflates by 2.32x.
    Deduplicating by message id collapses them back.
  * Tool results are recorded as `type: "user"`, so treating every user record as
    a new turn splits one long agentic turn into dozens.
"""
import json


def is_user_prompt(record):
    """Did the human actually type this, as opposed to a tool returning a result?"""
    if record.get("type") != "user":
        return False
    if record.get("toolUseResult") is not None:
        return False
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return False
    return True


def read_turn_tokens(path):
    """Tokens produced since the last real user prompt, and a marker for the turn.

    Returns (tokens, marker). The marker identifies the turn so it cannot be
    gambled twice; it is None when no prompt was found, which callers treat as
    "nothing to roll for".
    """
    turn_start = None
    seen = {}
    try:
        with open(path, "rb") as f:
            for raw in f:
                if not raw.endswith(b"\n"):
                    break  # a record still being written
                # Cheap prefilter. Matches bare tokens rather than
                # `"type":"user"` because the JSON may or may not have a space
                # after the colon, and a whitespace-sensitive filter silently
                # drops real prompts.
                if b'"user"' not in raw and b'"usage"' not in raw:
                    continue
                try:
                    record = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if is_user_prompt(record):
                    turn_start = record.get("uuid") or record.get("timestamp")
                    seen = {}
                    continue
                if record.get("type") != "assistant":
                    continue
                message = record.get("message") or {}
                key = message.get("id") or record.get("uuid")
                if key is None:
                    continue
                # Input + output, never cache. Cache reads dwarf real work
                # (measured 201M cache_read against 309k output in one session),
                # so counting them would track context size rather than effort.
                usage = message.get("usage") or {}
                seen[key] = (usage.get("output_tokens") or 0) + (
                    usage.get("input_tokens") or 0
                )
    except (IOError, OSError):
        return 0, None

    if turn_start is None:
        return 0, None
    return sum(seen.values()), turn_start
