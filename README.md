# cogctx — the Cognitive Context Protocol

**An open standard for telling AI tools how you are, so they can adapt how they help.**

Your copilot knows your codebase. Your writing assistant knows your document.
Neither knows that you just hit the 40th minute of deep flow — or that you're
running on fumes. cogctx is a tiny JSON packet that fixes that:

```json
{
  "schema": "cogctx/v1",
  "state": "deep_focus",
  "focus_score": 82,
  "directives": {
    "interrupt_ok": false,
    "verbosity": "terse",
    "complexity_budget": "high",
    "notifications": "silence"
  },
  "forecast": { "fatigue_eta_minutes": null, "note": "focus stable" },
  "as_of": "2026-08-12T17:03:00Z"
}
```

Any **producer** (keystroke-dynamics engine, wearable, webcam model, calendar
heuristic) can emit it. Any **consumer** (MCP-aware agent, IDE extension,
notification daemon) can act on it — without knowing how the state was
measured. The packet answers the three questions tools actually have:

1. **May I interrupt right now?** → `directives.interrupt_ok`
2. **How should I communicate?** → `verbosity`, `complexity_budget`, `prefer_small_steps`
3. **How long until the user hits a wall?** → `forecast.fatigue_eta_minutes`

## Try it in 30 seconds

No dependencies — Python 3.10+ stdlib only:

```bash
# start the reference server with a simulated focus session
python3 reference/cogctx_server.py serve --simulate

# in another terminal: ask the one question that matters
curl -s http://127.0.0.1:7710/v1/should-interrupt
```

```json
{
  "interrupt_ok": false,
  "state": "deep_focus",
  "reason": "User is in deep_focus — hold non-urgent interruptions; surface only real blockers."
}
```

Run the example consumer (a polite notification daemon):

```bash
python3 examples/consumer.py
```

### Expose it to AI agents over MCP

```bash
pip install mcp
python3 reference/cogctx_server.py mcp --simulate
```

This exposes `get_cognitive_state`, `should_interrupt_tool`, and
`how_to_help_tool` to any MCP client (Claude, Cursor, etc.).

### Wire in a real producer

Have your producer write a JSON state file — even a minimal one:

```json
{ "state": "fatigued", "focus_score": 34, "recent_scores": [58, 52, 47, 41, 38, 34] }
```

then point the server at it; it derives the directives, trend, and forecast:

```bash
python3 reference/cogctx_server.py serve --file /path/to/state.json
```

## Read the spec

- [SPEC.md](SPEC.md) — the full v1 specification (packet, states, directives, transports, privacy rules)
- [schema/cogctx.schema.json](schema/cogctx.schema.json) — JSON Schema for validation
- `python3 reference/cogctx_server.py validate <packet.json>` — stdlib-only conformance check

## Privacy is normative

A conforming producer **must not** put content in a packet — no keystrokes,
text, screenshots, window titles, or URLs. Packets are derived from
behavioral/physiological *metadata* only, and should stay on-device by
default. See [SPEC §6](SPEC.md#6-privacy-requirements). The packet exists to
make tools kinder, not to surveil: consumers must never punish the user for
any state.

## Status & provenance

cogctx v1 is a **draft open for review**. It generalizes the
`focuslens.cognitive_context/v1` packet shipped by FocusLens, a privacy-first
on-device focus engine whose MCP server exposes live cognitive state to AI
agents. This repo extracts that format so anyone can implement it.

**Wanted:** producers (wearables, HRV bridges, activity heuristics) and
consumers (agent frameworks, editors, notifiers). Open an issue with what
you're building — v1 is deliberately small, and feedback shapes v2.

## License

MIT — see [LICENSE](LICENSE).
