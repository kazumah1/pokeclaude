# Verifying an agent

Only Claude Code is verified end to end. This is how to settle the others, and what
counts as proof.

Two things have to be true, and they are separate:

1. **The agent invokes the hook.** Nothing else matters if it does not, and no
   amount of local testing can prove it — only running the real agent can.
2. **The banner reaches you.** The hook can fire and write to a channel the agent
   then discards.

`tools/check_host.py` proves the plugin side works. It cannot prove (1) or (2).
`tools/verify_agent.py` is for those.

## The three steps

```bash
python3 tools/verify_agent.py codex --arm     # raise the rate, start tracing
#   ... use the agent for a few turns ...
python3 tools/verify_agent.py codex           # read the verdict
python3 tools/verify_agent.py codex --disarm  # restore your settings
```

Arming sets the catch rate to 1 per 2,000 tokens so a catch lands within a few
turns rather than once a session, and enables a trace log. Your real catch rate is
backed up and restored by `--disarm`.

**Export the trace variable in the shell you launch the agent from**, or the trace
stays empty and the result is inconclusive rather than negative:

```bash
export POKECLAUDE_TRACE=~/.pokeclaude-verify.jsonl
codex        # or cursor, or whatever
```

For a GUI app, launch it from that terminal so it inherits the variable. An app
started from the dock will not see it.

## Reading the verdict

The report checks four stages in order. Where it stops tells you what is wrong:

| Stops at | Means |
|---|---|
| no events at all | hook not installed, or the variable was not exported — **inconclusive** |
| invoked, never rolls | the agent's payload carries no token usage — an adapter gap |
| rolls, never hits | working; just unlucky. Have a few more turns |
| emits a banner | works end to end — then judge whether you actually saw it |

The last stage is the one only you can answer. The report says which channel the
banner was written to; whether the agent renders that channel is the agent's choice,
not something the code can observe.

## Recording the result

If an agent passes all four stages **and** you saw the banner, it can move to
verified in the README table. If it stops earlier, the honest entry is what actually
happened — the current table is worded that way deliberately.

If it stops at "invoked, never rolls", the trace shows the payload keys the agent
sent. That is exactly what a new adapter entry needs, so it is worth pasting into an
issue.

## Per-agent notes

**Codex CLI** — installs via `codex plugin add` and registers a `Stop` hook. Event
names are PascalCase, unlike its prose docs. Never observed firing.

**Cursor** — the adapter is written from Cursor's hook docs and has never run. Its
`stop` event exists, but `user_message` is documented only on deny paths, so the
banner falls back to stderr and may not be displayed.

**Kiro** — the CLI preserves colour and renders correctly. Its IDE tool panel strips
colour and collapses output; use `POKECLAUDE_MONO=1` there.

**Copilot CLI** — hook events are undocumented. The adapter is a guess, so expect
stage 1 to fail until the real event name is known.
