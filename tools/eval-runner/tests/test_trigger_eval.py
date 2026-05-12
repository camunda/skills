"""Unit tests for trigger_eval.py.

We mock the run_eval.py subprocess via monkey-patching so tests run offline
and don't spend API credits. The shape we project from is fixed by upstream's
JSON contract (documented in tools/eval-runner/AGENTS.md); these tests pin
that contract on our end.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import trigger_eval  # noqa: E402


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def triggers_doc():
    return {
        "schema_version": 1,
        "skill": "demo",
        "discoverability": {"mode": "all_skills"},
        "positive": [
            {
                "id": "pos-a", "prompt": "do FEEL thing A",
                "expected_load": ["demo"], "expected_dependencies": [], "must_not_load": [],
            },
            {
                "id": "pos-b", "prompt": "do FEEL thing B",
                "expected_load": ["demo"], "expected_dependencies": [], "must_not_load": [],
            },
        ],
        "negative": [
            {
                "id": "neg-x", "prompt": "do unrelated thing X",
                "expected_load": [], "must_not_load": ["demo"],
            },
            {
                "id": "neg-y", "prompt": "do unrelated thing Y",
                "expected_load": [], "must_not_load": ["demo"],
            },
        ],
    }


# --- Conversion -------------------------------------------------------------


def test_to_run_eval_set_preserves_should_trigger(triggers_doc):
    out = trigger_eval._to_run_eval_set(triggers_doc)
    assert len(out) == 4
    assert {"query": "do FEEL thing A", "should_trigger": True} in out
    assert {"query": "do unrelated thing X", "should_trigger": False} in out


def test_duplicate_prompt_rejected(triggers_doc):
    triggers_doc["negative"][0]["prompt"] = triggers_doc["positive"][0]["prompt"]
    with pytest.raises(ValueError, match="duplicate prompt"):
        trigger_eval._to_run_eval_set(triggers_doc)


# --- F1 / aggregation -------------------------------------------------------


def test_aggregate_perfect_classifier():
    results = [
        {"should_trigger": True, "trigger_rate": 1.0},
        {"should_trigger": True, "trigger_rate": 0.66},
        {"should_trigger": False, "trigger_rate": 0.0},
        {"should_trigger": False, "trigger_rate": 0.33},
    ]
    agg = trigger_eval._aggregate(results)
    assert agg["precision"] == 1.0
    assert agg["recall"] == 1.0
    assert agg["f1"] == 1.0


def test_aggregate_with_false_positive():
    results = [
        {"should_trigger": True, "trigger_rate": 1.0},     # TP
        {"should_trigger": True, "trigger_rate": 1.0},     # TP
        {"should_trigger": False, "trigger_rate": 1.0},    # FP
        {"should_trigger": False, "trigger_rate": 0.0},    # TN
    ]
    agg = trigger_eval._aggregate(results)
    assert agg["precision"] == pytest.approx(2 / 3)
    assert agg["recall"] == 1.0
    assert agg["f1"] == pytest.approx(2 * (2/3) / (1 + 2/3))


def test_aggregate_no_positives():
    results = [
        {"should_trigger": False, "trigger_rate": 0.0},
        {"should_trigger": False, "trigger_rate": 0.33},
    ]
    agg = trigger_eval._aggregate(results)
    assert agg["precision"] == 0.0
    assert agg["recall"] == 0.0
    assert agg["f1"] == 0.0


# --- Projection -------------------------------------------------------------


def test_project_results_maps_back_to_case_ids(triggers_doc):
    upstream = {
        "skill_name": "demo",
        "description": "(unused)",
        "results": [
            {"query": "do FEEL thing A", "should_trigger": True,
             "trigger_rate": 1.0, "triggers": 3, "runs": 3, "pass": True},
            {"query": "do FEEL thing B", "should_trigger": True,
             "trigger_rate": 0.33, "triggers": 1, "runs": 3, "pass": False},
            {"query": "do unrelated thing X", "should_trigger": False,
             "trigger_rate": 0.0, "triggers": 0, "runs": 3, "pass": True},
            {"query": "do unrelated thing Y", "should_trigger": False,
             "trigger_rate": 1.0, "triggers": 3, "runs": 3, "pass": False},
        ],
        "summary": {"total": 4, "passed": 2, "failed": 2},
    }
    projected = trigger_eval.project_results(
        triggers_doc, upstream, runs=3, model="claude-opus-4-7", upstream_sha="deadbeef",
    )
    assert projected["skill"] == "demo"
    assert projected["positive_cases"] == 2
    assert projected["negative_cases"] == 2
    ids = {c["id"]: c for c in projected["per_case"]}
    assert ids["pos-a"]["pass"] is True
    assert ids["pos-a"]["actual_load"] == ["demo"]
    assert ids["pos-b"]["pass"] is False
    assert ids["pos-b"]["actual_load"] == []
    assert ids["neg-x"]["pass"] is True
    assert ids["neg-x"]["actual_load"] == []
    # neg-y is a false positive: should not have triggered, but did.
    assert ids["neg-y"]["pass"] is False
    assert ids["neg-y"]["actual_load"] == ["demo"]
    # F1: TP=1 (pos-a), FP=1 (neg-y), FN=1 (pos-b), TN=1 (neg-x)
    # precision = 0.5, recall = 0.5, F1 = 0.5
    assert projected["f1"] == 0.5
    assert projected["model"] == {"harness": "claude-opus-4-7"}
    assert projected["upstream_sha"] == "deadbeef"


# --- End-to-end with mocked subprocess -------------------------------------


def test_run_live_writes_summary_and_raw(tmp_path, triggers_doc, monkeypatch):
    # Scaffold a fake repo root with the SHA file + minimal skills/demo.
    repo_root = tmp_path
    skills_dir = repo_root / "skills" / "demo"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("---\nname: demo\ndescription: x\n---\n# demo\n")
    (repo_root / "skills" / "demo" / "evals").mkdir()
    (repo_root / "skills" / "demo" / "evals" / "triggers.json").write_text(
        json.dumps(triggers_doc), encoding="utf-8"
    )
    (repo_root / "tools" / "eval-runner").mkdir(parents=True)
    (repo_root / "tools" / "eval-runner" / ".skill-creator-sha").write_text("abc123\n")
    upstream_dir = (
        repo_root / "tools" / "external" / "anthropics-skills"
        / "skills" / "skill-creator" / "scripts"
    )
    upstream_dir.mkdir(parents=True)
    (upstream_dir / "run_eval.py").write_text("# stub")

    fake_upstream_output = {
        "skill_name": "demo",
        "description": "x",
        "results": [
            {"query": c["prompt"], "should_trigger": True, "trigger_rate": 1.0,
             "triggers": 3, "runs": 3, "pass": True}
            for c in triggers_doc["positive"]
        ] + [
            {"query": c["prompt"], "should_trigger": False, "trigger_rate": 0.0,
             "triggers": 0, "runs": 3, "pass": True}
            for c in triggers_doc["negative"]
        ],
        "summary": {"total": 4, "passed": 4, "failed": 0},
    }

    def fake_invoke(repo_root_, skill, eval_set, runs, workers, timeout, model):
        # Sanity-check we passed the right shape upstream.
        assert skill == "demo"
        assert {"query": "do FEEL thing A", "should_trigger": True} in eval_set
        assert runs == 3
        return fake_upstream_output

    monkeypatch.setattr(trigger_eval, "invoke_run_eval", fake_invoke)

    iteration_dir = repo_root / "evals" / "demo" / "iteration-1"
    iteration_dir.mkdir(parents=True)
    summary = trigger_eval.run_live(
        repo_root, "demo", iteration_dir, runs=3,
    )
    assert summary["f1"] == 1.0
    assert (iteration_dir / "triggers" / "summary.json").exists()
    assert (iteration_dir / "triggers" / "run_eval_raw.json").exists()
    written = json.loads((iteration_dir / "triggers" / "summary.json").read_text())
    assert written["upstream_sha"] == "abc123"


def test_run_live_errors_when_upstream_missing(tmp_path, triggers_doc):
    repo_root = tmp_path
    skills_dir = repo_root / "skills" / "demo" / "evals"
    skills_dir.mkdir(parents=True)
    (skills_dir / "triggers.json").write_text(json.dumps(triggers_doc))
    (repo_root / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: x\n---\n"
    )
    iteration_dir = repo_root / "evals" / "demo" / "iteration-1"
    iteration_dir.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="run_eval.py not found"):
        trigger_eval.run_live(repo_root, "demo", iteration_dir, runs=1)
