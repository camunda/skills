"""Tests for baseline.py — load, validate, diff, markdown rendering.

Schema validation is exercised against synthetic baseline.json contents so a
breaking schema change in tools/skill-lint/schemas/baseline.schema.json
fails the runner suite too.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import baseline  # noqa: E402


def _baseline_obj(
    *,
    skill="demo",
    f1=0.91, with_=0.88, without=0.42,
    n_cases=4, n_trials=12,
):
    return {
        "schema_version": 1,
        "skill": skill,
        "established_at": "2026-05-01T12:00:00+00:00",
        "established_by": "abc1234",
        "source_iteration": "evals/demo/iteration-3",
        "model": {
            "provider": "anthropic",
            "id": "claude-opus-4-7",
            "harness": "claude-agent-sdk",
            "judge": "claude-sonnet-4-6",
        },
        "trials_per_case": n_trials // max(n_cases, 1),
        "triggers": {
            "f1": f1, "precision": f1, "recall": f1,
            "positive_cases": 10, "negative_cases": 10,
        },
        "quality": {
            "with_skill": {"pass_rate": with_, "n_cases": n_cases, "n_trials": n_trials},
            "without_skill": {"pass_rate": without, "n_cases": n_cases, "n_trials": n_trials},
            "delta_pp": (with_ - without) * 100.0,
            "per_case": [],
        },
        "regression_thresholds": {
            "with_skill_pass_rate_drop_pp": 5.0,
            "trigger_f1_drop_pp": 5.0,
            "sustained_runs": 2,
            "noise_floor_pp": round(100.0 / n_trials, 2),
        },
    }


def _candidate(*, f1=0.91, with_=0.88, without=0.42, n_cases=4, n_trials=12):
    return {
        "skill": "demo",
        "iteration": "iteration-4",
        "triggers": {
            "f1": f1, "precision": f1, "recall": f1,
            "positive_cases": 10, "negative_cases": 10,
        },
        "quality": {
            "with_skill": {"pass_rate": with_, "n_cases": n_cases, "n_trials": n_trials},
            "without_skill": {"pass_rate": without, "n_cases": n_cases, "n_trials": n_trials},
            "delta_pp": (with_ - without) * 100.0,
        },
    }


def _write_baseline(tmp_path: Path, obj: dict, skill: str = "demo") -> Path:
    p = tmp_path / "skills" / skill / "evals" / "baseline.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return p


# --- Schema validation -----------------------------------------------------


def test_validate_passes_on_well_formed_baseline():
    baseline.validate(_baseline_obj())  # should not raise


def test_validate_rejects_extra_field():
    obj = _baseline_obj()
    obj["bonus"] = "no schema"
    with pytest.raises(ValueError, match="schema violations"):
        baseline.validate(obj)


def test_validate_rejects_pass_rate_above_one():
    obj = _baseline_obj()
    obj["quality"]["with_skill"]["pass_rate"] = 1.5
    with pytest.raises(ValueError, match="schema violations"):
        baseline.validate(obj)


def test_load_returns_none_when_missing(tmp_path):
    assert baseline.load(tmp_path, "absent") is None


def test_load_rejects_unsupported_schema_version(tmp_path):
    obj = _baseline_obj()
    obj["schema_version"] = 99
    _write_baseline(tmp_path, obj)
    with pytest.raises(ValueError, match="unsupported schema_version"):
        baseline.load(tmp_path, "demo")


def test_load_round_trip(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    assert b is not None
    assert b.skill == "demo"
    assert b.with_skill_pass_rate == 0.88
    assert b.trigger_f1 == 0.91


# --- Diff -------------------------------------------------------------------


def test_diff_no_regression_when_metrics_stable(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    d = baseline.diff(b, _candidate())
    assert not d.regression
    assert not d.warning


def test_diff_flags_regression_on_quality_drop(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    d = baseline.diff(b, _candidate(with_=0.80))   # 8pp drop
    assert d.regression


def test_diff_flags_regression_on_f1_drop(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    d = baseline.diff(b, _candidate(f1=0.84))   # 7pp drop
    assert d.regression


def test_diff_warns_at_3pp(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    d = baseline.diff(b, _candidate(with_=0.85))   # 3pp drop
    assert not d.regression
    assert d.warning


def test_diff_noise_floor_from_candidate(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    d = baseline.diff(b, _candidate(n_cases=4, n_trials=12))
    # 100 / (4*12) ≈ 2.083
    assert abs(d.noise_floor_pp - 100.0 / 48) < 0.001


# --- Markdown ---------------------------------------------------------------


def test_markdown_ok_status(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    d = baseline.diff(b, _candidate())
    md = baseline.render_markdown(d)
    assert "## demo — eval delta" in md
    assert "**Status: ok**" in md
    assert "trigger F1" in md
    assert "with_skill pass rate" in md


def test_markdown_regression_status_with_rationale(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    d = baseline.diff(b, _candidate(with_=0.80))
    md = baseline.render_markdown(d)
    assert "**Status: regression**" in md
    assert "`with_skill` dropped" in md
    assert "limit 5.0pp" in md


def test_markdown_warn_status_at_3pp(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    d = baseline.diff(b, _candidate(with_=0.85))
    md = baseline.render_markdown(d)
    assert "**Status: warn**" in md


def test_markdown_arrow_directions(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    d = baseline.diff(b, _candidate(f1=0.95, with_=0.92))
    md = baseline.render_markdown(d)
    # Both metrics improved → up arrows on both rows.
    assert "▲ +4.0pp" in md or "▲ +4.0pp" in md  # f1 +4pp
    assert "▲ +4.0pp" in md  # with +4pp


def test_markdown_includes_noise_floor(tmp_path):
    obj = _baseline_obj()
    _write_baseline(tmp_path, obj)
    b = baseline.load(tmp_path, "demo")
    d = baseline.diff(b, _candidate())
    md = baseline.render_markdown(d)
    assert "Noise floor:" in md
    assert "pp" in md
