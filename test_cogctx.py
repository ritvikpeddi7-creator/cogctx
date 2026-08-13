"""Tests for the cogctx reference implementation. Run:  python3 -m pytest"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "reference"))

from cogctx_server import (  # noqa: E402
    build_packet,
    derive_directives,
    forecast_fatigue,
    how_to_help,
    should_interrupt,
    validate_packet,
)

EXAMPLES = pathlib.Path(__file__).parent / "examples"


def test_example_packet_conforms():
    packet = json.loads((EXAMPLES / "packet.example.json").read_text())
    assert validate_packet(packet) == []


def test_minimal_producer_state_builds_conforming_packet():
    raw = json.loads((EXAMPLES / "producer_state.example.json").read_text())
    packet = build_packet(raw)
    assert validate_packet(packet) == []
    assert packet["state"] == "fatigued"
    assert packet["directives"]["verbosity"] == "scaffolded"
    assert packet["directives"]["prefer_small_steps"] is True


def test_deep_focus_blocks_interruptions():
    packet = build_packet({"state": "deep_focus", "focus_score": 85})
    answer = should_interrupt(packet)
    assert answer["interrupt_ok"] is False
    assert "deep_focus" in answer["reason"]


def test_unknown_state_is_safe_default():
    packet = build_packet({"state": "something-weird"})
    assert packet["state"] == "unknown"
    assert packet["directives"]["interrupt_ok"] is True
    assert how_to_help(packet)["verbosity"] == "normal"


def test_declining_scores_produce_finite_fatigue_eta():
    fc = forecast_fatigue([70, 64, 58, 52, 47, 42])
    assert isinstance(fc["fatigue_eta_minutes"], int)
    assert fc["fatigue_eta_minutes"] >= 0


def test_stable_scores_predict_no_fatigue():
    assert forecast_fatigue([80, 81, 80, 82, 81, 82])["fatigue_eta_minutes"] is None


def test_directive_policy_matches_spec_table():
    assert derive_directives("deep_focus", 85, "stable")["notifications"] == "silence"
    assert derive_directives("fatigued", 30, "declining")["complexity_budget"] == "low"
    assert derive_directives("stressed", 50, "stable")["prefer_small_steps"] is True


def test_validator_catches_violations():
    bad = {"schema": "cogctx/v1", "state": "deep_focus", "as_of": "2026-01-01T00:00:00Z",
           "directives": {"interrupt_ok": "nope", "verbosity": "shouty"},
           "focus_score": 250}
    errors = validate_packet(bad)
    assert len(errors) == 3
