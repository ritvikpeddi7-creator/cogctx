#!/usr/bin/env python3
"""
cogctx reference server — a minimal, dependency-free implementation of the
Cognitive Context Protocol (cogctx/v1). See ../SPEC.md.

Providers (where the state comes from):
  --file PATH    read a JSON state file written by any producer. Either a full
                 cogctx packet, or a minimal raw dict:
                   {"state": "deep_focus", "focus_score": 82, "confidence": 0.9,
                    "recent_scores": [80, 81, 83, 82]}
                 The server fills in directives, trend, and forecast.
  --simulate     emit a plausible synthetic focus session (demo / development).

Transports:
  serve          HTTP binding on 127.0.0.1 (default port 7710)
  mcp            MCP binding (requires `pip install mcp`)
  show           print the current packet once and exit
  validate PATH  check a packet file against the v1 rules (stdlib only)

Examples:
  python3 cogctx_server.py serve --simulate
  python3 cogctx_server.py serve --file /tmp/my_state.json --port 7710
  python3 cogctx_server.py mcp --file /tmp/my_state.json
  python3 cogctx_server.py validate ../examples/packet.example.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCHEMA = "cogctx/v1"
STATES = ("deep_focus", "normal_focus", "distracted", "fatigued", "stressed", "unknown")
FATIGUE_FLOOR = 40          # focus_score treated as the fatigue threshold
SAMPLE_SECONDS = 10         # assumed spacing of recent_scores samples
STALE_SECONDS = 120

# ── Reference directive policy (SPEC §3.3) ──────────────────────────────────

_POLICY = {
    "deep_focus":   dict(interrupt_ok=False, verbosity="terse",      complexity_budget="high",   notifications="silence"),
    "normal_focus": dict(interrupt_ok=True,  verbosity="normal",     complexity_budget="medium", notifications="normal"),
    "distracted":   dict(interrupt_ok=True,  verbosity="normal",     complexity_budget="medium", notifications="batch"),
    "fatigued":     dict(interrupt_ok=True,  verbosity="scaffolded", complexity_budget="low",    notifications="batch"),
    "stressed":     dict(interrupt_ok=True,  verbosity="normal",     complexity_budget="low",    notifications="normal"),
    "unknown":      dict(interrupt_ok=True,  verbosity="normal",     complexity_budget="medium", notifications="normal"),
}


def derive_directives(state: str, score: int | None, trend: str) -> dict:
    base = dict(_POLICY.get(state, _POLICY["unknown"]))
    base["prefer_small_steps"] = state in ("fatigued", "stressed")
    base["suggest_break"] = state == "fatigued" or (
        trend == "declining" and score is not None and score < FATIGUE_FLOOR + 5
    )
    return base


def trend_of(recent: list[int]) -> str:
    if len(recent) < 3:
        return "stable"
    delta = recent[-1] - recent[max(0, len(recent) - 4)]
    if delta <= -6:
        return "declining"
    if delta >= 6:
        return "improving"
    return "stable"


def forecast_fatigue(recent: list[int]) -> dict:
    """Linear extrapolation of the recent score slope to the fatigue floor."""
    if len(recent) < 4:
        return {"fatigue_eta_minutes": None, "note": "warming up — need a little more data"}
    window = recent[-6:]
    slope = (window[-1] - window[0]) / (len(window) - 1)
    if window[-1] <= FATIGUE_FLOOR:
        return {"fatigue_eta_minutes": 0, "note": "already at/below the fatigue floor"}
    if slope >= -0.1:
        return {"fatigue_eta_minutes": None, "note": "focus stable — no fatigue predicted soon"}
    minutes = max(0, round((window[-1] - FATIGUE_FLOOR) / -slope * SAMPLE_SECONDS / 60))
    return {
        "fatigue_eta_minutes": minutes,
        "note": f"focus trending down ~{-slope:.1f} pts/sample; floor (~{FATIGUE_FLOOR}) in ~{minutes} min",
    }


def build_packet(raw: dict) -> dict:
    """Raw producer dict (or full packet) → conforming cogctx/v1 packet."""
    state = raw.get("state", "unknown")
    if state not in STATES:
        state = "unknown"
    score = raw.get("focus_score", raw.get("score"))
    score = None if score is None else max(0, min(100, int(score)))
    recent = [int(s) for s in (raw.get("recent_scores") or []) if s is not None]
    trend = raw.get("trend") or trend_of(recent)

    packet = {
        "schema": SCHEMA,
        "state": state,
        "focus_score": score,
        "confidence": round(float(raw.get("confidence", 0.0) or 0.0), 2),
        "trend": trend,
        "directives": raw.get("directives") or derive_directives(state, score, trend),
        "forecast": raw.get("forecast") or forecast_fatigue(recent),
        "as_of": raw.get("as_of") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": raw.get("provider") or {"name": "cogctx-reference", "version": "0.1.0"},
        "privacy": raw.get("privacy")
        or "behavioral metadata only — no keystrokes, text, or app content",
    }
    return packet


# ── Single-question views (SPEC §4) ─────────────────────────────────────────

def should_interrupt(packet: dict) -> dict:
    ok = bool(packet["directives"].get("interrupt_ok", True))
    state = packet["state"]
    reason = (
        f"User is in {state} — hold non-urgent interruptions; surface only real blockers."
        if not ok
        else f"User is in {state} — fine to engage normally."
    )
    return {"interrupt_ok": ok, "state": state, "reason": reason}


_VERBOSITY_REASON = {
    "terse": "User is in flow — keep replies short and don't add cognitive load.",
    "scaffolded": "User is fatigued — explain more and break work into small, safe steps.",
    "normal": "User is at a normal working level — engage as usual.",
}


def how_to_help(packet: dict) -> dict:
    d = packet["directives"]
    verbosity = d.get("verbosity", "normal")
    return {
        "verbosity": verbosity,
        "complexity_budget": d.get("complexity_budget", "medium"),
        "prefer_small_steps": bool(d.get("prefer_small_steps", False)),
        "notifications": d.get("notifications", "normal"),
        "state": packet["state"],
        "reason": _VERBOSITY_REASON.get(verbosity, _VERBOSITY_REASON["normal"]),
    }


# ── Providers ────────────────────────────────────────────────────────────────

class FileProvider:
    """Reads a JSON state file on every request. Missing/broken file → unknown."""

    def __init__(self, path: str):
        self.path = path

    def get(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                return build_packet(json.load(f))
        except (OSError, ValueError):
            return build_packet({"state": "unknown"})


class SimulatedProvider:
    """A plausible synthetic focus session: warm-up → flow → gradual fatigue."""

    def __init__(self):
        self.start = time.monotonic()
        self.scores: list[int] = []

    def get(self) -> dict:
        t = (time.monotonic() - self.start) / 60  # minutes elapsed
        score = round(55 + 35 * math.sin(min(t / 25, 1.0) * math.pi / 2) - max(0, t - 35) * 1.2)
        score = max(15, min(95, score))
        self.scores = (self.scores + [score])[-12:]
        if score >= 78:
            state = "deep_focus"
        elif score >= 55:
            state = "normal_focus"
        elif score >= FATIGUE_FLOOR:
            state = "distracted"
        else:
            state = "fatigued"
        return build_packet({
            "state": state,
            "focus_score": score,
            "confidence": 0.85,
            "recent_scores": self.scores,
            "provider": {"name": "cogctx-simulator", "version": "0.1.0"},
        })


# ── Validation (stdlib-only structural check) ───────────────────────────────

def validate_packet(packet: dict) -> list[str]:
    """Return a list of violations (empty = conforming)."""
    errors = []
    if packet.get("schema") != SCHEMA:
        errors.append(f'schema must be "{SCHEMA}", got {packet.get("schema")!r}')
    if packet.get("state") not in STATES:
        errors.append(f"state must be one of {STATES}, got {packet.get('state')!r}")
    if not isinstance(packet.get("as_of"), str):
        errors.append("as_of (ISO 8601 string) is required")
    d = packet.get("directives")
    if not isinstance(d, dict):
        errors.append("directives object is required")
    else:
        if not isinstance(d.get("interrupt_ok"), bool):
            errors.append("directives.interrupt_ok (boolean) is required")
        for field, allowed in (
            ("verbosity", ("terse", "normal", "scaffolded")),
            ("complexity_budget", ("low", "medium", "high")),
            ("notifications", ("silence", "batch", "normal")),
        ):
            if field in d and d[field] not in allowed:
                errors.append(f"directives.{field} must be one of {allowed}, got {d[field]!r}")
    score = packet.get("focus_score")
    if score is not None and not (isinstance(score, int) and 0 <= score <= 100):
        errors.append(f"focus_score must be an integer 0–100 or null, got {score!r}")
    conf = packet.get("confidence")
    if conf is not None and not (isinstance(conf, (int, float)) and 0 <= conf <= 1):
        errors.append(f"confidence must be a number 0–1, got {conf!r}")
    if "trend" in packet and packet["trend"] not in ("improving", "stable", "declining"):
        errors.append(f"trend must be improving|stable|declining, got {packet['trend']!r}")
    return errors


# ── HTTP binding ─────────────────────────────────────────────────────────────

def serve_http(provider, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            packet = provider.get()
            routes = {
                "/v1/context": packet,
                "/v1/should-interrupt": should_interrupt(packet),
                "/v1/how-to-help": how_to_help(packet),
            }
            body = routes.get(self.path.rstrip("/") or "/v1/context")
            if body is None:
                self.send_error(404, "unknown endpoint — see /v1/context")
                return
            data = json.dumps(body, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):  # keep the terminal quiet
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"cogctx reference server → http://127.0.0.1:{port}/v1/context")
    server.serve_forever()


# ── MCP binding ──────────────────────────────────────────────────────────────

def serve_mcp(provider) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError:
        sys.exit("The MCP binding needs the MCP SDK:  pip install mcp")

    mcp = FastMCP("cogctx")

    @mcp.tool()
    def get_cognitive_state() -> dict:
        """The user's live cognitive context (cogctx/v1 packet). Adapt to
        directives.interrupt_ok, directives.verbosity, and the fatigue forecast."""
        return provider.get()

    @mcp.tool()
    def should_interrupt_tool() -> dict:
        """Call before surfacing anything non-urgent. Returns
        {interrupt_ok, state, reason}; false means the user is in deep flow."""
        return should_interrupt(provider.get())

    @mcp.tool()
    def how_to_help_tool() -> dict:
        """How to adapt right now: {verbosity, complexity_budget,
        prefer_small_steps, notifications, state, reason}."""
        return how_to_help(provider.get())

    @mcp.resource("cogctx://state")
    def state_resource() -> str:
        return json.dumps(provider.get(), indent=2)

    mcp.run()


# ── CLI ──────────────────────────────────────────────────────────────────────

def make_provider(args):
    if args.file:
        return FileProvider(args.file)
    return SimulatedProvider()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("serve", "mcp", "show"):
        s = sub.add_parser(name)
        s.add_argument("--file", help="JSON state file written by a producer")
        s.add_argument("--simulate", action="store_true", help="synthetic demo session (default)")
        if name == "serve":
            s.add_argument("--port", type=int, default=7710)
    v = sub.add_parser("validate")
    v.add_argument("path")
    args = p.parse_args()

    if args.cmd == "validate":
        with open(args.path, encoding="utf-8") as f:
            errors = validate_packet(json.load(f))
        if errors:
            print("NOT conforming:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)
        print("conforming cogctx/v1 packet ✓")
        return

    provider = make_provider(args)
    if args.cmd == "serve":
        serve_http(provider, args.port)
    elif args.cmd == "mcp":
        serve_mcp(provider)
    else:
        print(json.dumps(provider.get(), indent=2))


if __name__ == "__main__":
    main()
