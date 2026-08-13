# cogctx — Cognitive Context Protocol

**Version:** v1 (draft)
**Schema identifier:** `cogctx/v1`
**Status:** Draft for community review

---

## 1. Motivation

AI tools adapt to *what* you're working on, but not to *how you are* while
working on it. A coding copilot interrupts you mid-flow with a refactor
suggestion; a writing assistant dumps a wall of text on someone who is already
fatigued; a notification fires during the first deep-focus block of the day.

cogctx defines a small, vendor-neutral **cognitive context packet**: a JSON
object that describes the user's current cognitive state and — more
importantly — what an AI tool should *do* about it. Any producer (a
keystroke-dynamics engine, a wearable, a calendar heuristic, a webcam model)
can emit it, and any consumer (an MCP-aware agent, an IDE extension, a
notification daemon) can act on it without knowing how the state was measured.

The design goal is that a consumer never needs to interpret raw signals. The
packet answers three questions directly:

1. **May I interrupt right now?**
2. **How should I communicate?** (verbosity, complexity, step size)
3. **How long until the user hits a wall?**

## 2. Terminology

- **Producer** — software that estimates cognitive state and emits packets.
- **Consumer** — software that reads packets and adapts its behavior.
- The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are to be
  interpreted as described in RFC 2119.

## 3. The packet

A cogctx packet is a single JSON object.

```json
{
  "schema": "cogctx/v1",
  "state": "deep_focus",
  "focus_score": 82,
  "confidence": 0.9,
  "trend": "stable",
  "directives": {
    "interrupt_ok": false,
    "verbosity": "terse",
    "complexity_budget": "high",
    "notifications": "silence",
    "prefer_small_steps": false,
    "suggest_break": false
  },
  "forecast": {
    "fatigue_eta_minutes": null,
    "note": "focus stable — no fatigue predicted soon"
  },
  "as_of": "2026-08-12T17:03:00Z",
  "provider": { "name": "focuslens", "version": "1.4.0" },
  "privacy": "on-device; behavioral metadata only — no keystrokes, text, or app content"
}
```

### 3.1 Top-level fields

| Field         | Type            | Required | Description |
|---------------|-----------------|----------|-------------|
| `schema`      | string          | MUST     | Exactly `"cogctx/v1"`. |
| `state`       | string enum     | MUST     | See §3.2. |
| `directives`  | object          | MUST     | See §3.3. |
| `as_of`       | string (ISO 8601) | MUST   | When the state was estimated. Consumers SHOULD treat packets older than 120 seconds as stale (§5). |
| `focus_score` | integer 0–100 or null | SHOULD | Higher = more focused. `null` when the producer has no scalar score. |
| `confidence`  | number 0–1      | SHOULD   | Producer's confidence in `state`. |
| `trend`       | string enum     | MAY      | `"improving"`, `"stable"`, or `"declining"` over the last few minutes. |
| `forecast`    | object          | MAY      | See §3.4. |
| `provider`    | object          | MAY      | `{ "name": string, "version": string }`, identifying the producer. |
| `privacy`     | string          | MAY      | Human-readable statement of what the estimate was derived from. |

Unknown top-level fields MUST be ignored by consumers (forward compatibility).

### 3.2 States

`state` MUST be one of:

| Token          | Meaning |
|----------------|---------|
| `deep_focus`   | Sustained, high-quality flow. The most protected state. |
| `normal_focus` | Ordinary productive engagement. |
| `distracted`   | Fragmented attention; frequent context switching. |
| `fatigued`     | Depleted; error-prone; needs scaffolding or rest. |
| `stressed`     | Rushed or under pressure; elevated error risk. |
| `unknown`      | The producer cannot estimate state (cold start, no signal, consent withheld). |

Producers with richer internal taxonomies MUST map to these six tokens at the
boundary. Consumers MUST treat unrecognized tokens as `unknown`.

### 3.3 Directives

The actionable heart of the packet. Producers derive these from state so that
consumers don't each reinvent the policy.

| Field                | Type        | Required | Description |
|----------------------|-------------|----------|-------------|
| `interrupt_ok`       | boolean     | MUST     | Whether a non-urgent interruption is acceptable right now. |
| `verbosity`          | enum        | SHOULD   | `"terse"` (in flow — minimize added load), `"normal"`, or `"scaffolded"` (fatigued — explain more, smaller pieces). |
| `complexity_budget`  | enum        | SHOULD   | `"low"`, `"medium"`, or `"high"` — how much *new* cognitive complexity the tool may introduce. |
| `notifications`      | enum        | MAY      | `"silence"`, `"batch"`, or `"normal"` — posture for the OS or tool. |
| `prefer_small_steps` | boolean     | MAY      | Copilots SHOULD prefer small, low-risk changes when true. |
| `suggest_break`      | boolean     | MAY      | The tool MAY proactively suggest a break when true. |

**Reference policy** (the mapping used by the reference server; producers MAY
substitute their own):

| state          | interrupt_ok | verbosity  | complexity_budget | notifications | prefer_small_steps |
|----------------|--------------|------------|-------------------|---------------|--------------------|
| `deep_focus`   | false        | terse      | high              | silence       | false              |
| `normal_focus` | true         | normal     | medium            | normal        | false              |
| `distracted`   | true         | normal     | medium            | batch         | false              |
| `fatigued`     | true         | scaffolded | low               | batch         | true               |
| `stressed`     | true         | normal     | low               | normal        | true               |
| `unknown`      | true         | normal     | medium            | normal        | false              |

### 3.4 Forecast

Optional short-horizon fatigue prediction:

| Field                | Type              | Description |
|----------------------|-------------------|-------------|
| `fatigue_eta_minutes`| integer ≥ 0 or null | Estimated minutes until the user reaches their fatigue floor. `null` = no fatigue predicted / not enough data. `0` = already there. |
| `note`               | string            | Human-readable explanation. |

Consumers MAY use this to front-load hard or risky work while the user is
still sharp.

## 4. Transports

cogctx is transport-agnostic. Two bindings are defined for v1; a producer
SHOULD offer at least one.

### 4.1 HTTP binding

A local loopback server exposing:

| Endpoint                  | Returns |
|---------------------------|---------|
| `GET /v1/context`         | The full packet (§3). |
| `GET /v1/should-interrupt`| `{ "interrupt_ok": bool, "state": string, "reason": string }` |
| `GET /v1/how-to-help`     | `{ "verbosity", "complexity_budget", "prefer_small_steps", "notifications", "state", "reason" }` |

Responses are `application/json`. Servers SHOULD bind to `127.0.0.1` only.

### 4.2 MCP binding

An [MCP](https://modelcontextprotocol.io) server exposing tools with these
names and semantics:

| Tool                    | Returns |
|-------------------------|---------|
| `get_cognitive_state()` | The full packet. |
| `should_interrupt()`    | Same shape as `GET /v1/should-interrupt`. |
| `how_to_help()`         | Same shape as `GET /v1/how-to-help`. |

and a resource `cogctx://state` containing the packet as JSON text.

## 5. Consumer requirements

- Consumers MUST treat a missing, stale (`as_of` older than ~120 s), or
  `unknown` packet as *no signal* and behave as they would without cogctx.
  Absence of a packet is never an error.
- Consumers MUST NOT punish the user for any state (e.g., surfacing
  "you seem distracted" to third parties). The packet exists to make tools
  kinder, not to surveil.
- When `interrupt_ok` is false, consumers SHOULD hold all non-urgent output.
  Genuine blockers MAY still be surfaced.

## 6. Privacy requirements

These are normative. A producer that violates them is not a conforming cogctx
producer, regardless of packet shape.

1. Packets MUST NOT contain content: no keystrokes, text, screenshots, window
   titles, URLs, file names, or audio/video derived transcripts.
2. Packets MUST be derived from behavioral or physiological *metadata*
   (timing, rhythm, activity levels, heart-rate variability, self-report).
3. Producers SHOULD keep raw signals on-device and emit only the derived
   packet. Producers that transmit packets off-device MUST require explicit
   opt-in.
4. Producers SHOULD populate the `privacy` field with an honest, human-readable
   description of the derivation.

## 7. Versioning

The `schema` field carries the version. Within `v1`, changes are additive
only: new optional fields may be added; existing fields never change meaning
or type. Breaking changes require `cogctx/v2`.

## 8. Provenance

cogctx v1 generalizes the `focuslens.cognitive_context/v1` packet shipped by
[FocusLens](https://github.com/NotGalacticFire/NeuroSense), a privacy-first
on-device focus engine, whose MCP server was (to our knowledge) the first to
expose live cognitive state to AI agents. This spec extracts that format so
any producer or consumer can implement it. FocusLens is the first conforming
producer: it serves packets at `GET /cogctx` (alias `GET /v1/context`) and via
the `get_cogctx_state` MCP tool and `cogctx://state` resource.
