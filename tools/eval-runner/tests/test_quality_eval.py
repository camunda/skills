"""Tests for quality_eval.py — aggregation logic in isolation.

The async orchestration that calls the SDK is exercised in test_sdk_runner.
Here we focus on the pure aggregation function so a regression in pass-rate
math gets caught even when no API key is around.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import quality_eval  # noqa: E402
from quality_eval import TrialOutcome, aggregate  # noqa: E402


def _trial(arm: str, case: str, trial: int, passed: bool, cost: float = 0.01) -> TrialOutcome:
    return TrialOutcome(
        arm=arm, case_id=case, trial=trial, passed=passed,
        grading_pass_rate=1.0 if passed else 0.0,
        cost_usd=cost, duration_ms=100,
        skill_loads_via_tool=[], skill_loads_via_read=[],
    )


def test_aggregate_perfect_with_skill_zero_without():
    trials = []
    for case in ("c1", "c2"):
        for t in (1, 2, 3):
            trials.append(_trial("with_skill", case, t, passed=True))
            trials.append(_trial("without_skill", case, t, passed=False))
    agg = aggregate(trials)
    assert agg["with_skill"]["pass_rate"] == 1.0
    assert agg["without_skill"]["pass_rate"] == 0.0
    assert agg["delta_pp"] == 100.0
    assert agg["with_skill"]["n_cases"] == 2
    assert agg["with_skill"]["n_trials"] == 3
    # Per-case breakdown.
    by_case = {c["id"]: c for c in agg["per_case"]}
    assert by_case["c1"] == {"id": "c1", "with_skill": 1.0, "without_skill": 0.0}


def test_aggregate_partial_pass():
    trials = [
        _trial("with_skill", "c1", 1, True),
        _trial("with_skill", "c1", 2, True),
        _trial("with_skill", "c1", 3, False),  # 2/3
        _trial("without_skill", "c1", 1, False),
        _trial("without_skill", "c1", 2, False),
        _trial("without_skill", "c1", 3, True),  # 1/3
    ]
    agg = aggregate(trials)
    assert agg["with_skill"]["pass_rate"] == pytest.approx(2 / 3, abs=0.001)
    assert agg["without_skill"]["pass_rate"] == pytest.approx(1 / 3, abs=0.001)
    assert agg["delta_pp"] == pytest.approx(33.33, abs=0.01)


def test_aggregate_sums_cost():
    trials = [
        _trial("with_skill", "c1", 1, True, cost=0.05),
        _trial("with_skill", "c1", 2, True, cost=0.06),
        _trial("without_skill", "c1", 1, False, cost=0.04),
    ]
    agg = aggregate(trials)
    assert agg["estimated_cost_usd"] == pytest.approx(0.15, abs=0.001)


def test_aggregate_handles_missing_cost():
    trials = [
        TrialOutcome(arm="with_skill", case_id="c1", trial=1, passed=True,
                     grading_pass_rate=1.0, cost_usd=None, duration_ms=10,
                     skill_loads_via_tool=[], skill_loads_via_read=[]),
    ]
    agg = aggregate(trials)
    assert agg["estimated_cost_usd"] == 0.0


def test_aggregate_empty_input():
    agg = aggregate([])
    assert agg["with_skill"]["pass_rate"] == 0.0
    assert agg["without_skill"]["pass_rate"] == 0.0
    assert agg["delta_pp"] == 0.0
    assert agg["per_case"] == []


def test_quality_pass_threshold_constant_documented():
    # The aggregation tier respects a per-trial threshold; ensure it lives in
    # one place so contributors can find it.
    assert quality_eval.QUALITY_PASS_THRESHOLD == 0.5
