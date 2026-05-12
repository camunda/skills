"""Tier-1 trigger eval: wraps anthropics/skills' scripts/run_eval.py.

We do NOT reimplement the trial loop or trigger detection — `run_eval.py`
already shells out to ``claude -p`` and detects skill loads from the
stream-json transcript. This module:

  1. Loads our triggers.json.
  2. Converts it to ``run_eval.py``'s eval-set format
     (``[{query, should_trigger}, ...]``) in a temp file.
  3. Subprocesses ``run_eval.py``.
  4. Parses the single-JSON-object stdout.
  5. Projects it into our summary.json shape, computing F1 / precision /
     recall over the positive/negative split.

Output shape (returned dict, also written to ``iteration-N/triggers/summary.json``):

    {
      "skill": "camunda-feel",
      "trials_per_case": 3,
      "f1": 0.91, "precision": 0.93, "recall": 0.89,
      "positive_cases": 10, "negative_cases": 10,
      "per_case": [
        {"id": "...", "kind": "positive", "expected_load": [...],
         "must_not_load": [...], "trigger_rate": 0.66, "triggers": 2,
         "runs": 3, "pass": true, "actual_load": ["camunda-feel"]}
      ],
      "model": {"harness": "<id>"},
      "upstream_sha": "<run_eval.py SHA>"
    }

`actual_load` is a coarse approximation: ``[skill]`` if the run triggered the
target skill, ``[]`` otherwise. Tracking which OTHER skills loaded is a
follow-up — see tools/eval-runner/AGENTS.md.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def load_triggers(repo_root: Path, skill: str) -> dict[str, Any] | None:
    p = repo_root / "skills" / skill / "evals" / "triggers.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _to_run_eval_set(triggers: dict[str, Any]) -> list[dict[str, Any]]:
    """Project triggers.json into run_eval.py's eval-set format."""
    items: list[dict[str, Any]] = []
    seen_queries: set[str] = set()
    for case in triggers.get("positive", []):
        q = case["prompt"]
        if q in seen_queries:
            raise ValueError(
                f"duplicate prompt across triggers cases (case id={case['id']!r}); "
                f"run_eval.py keys results by query string so prompts must be unique"
            )
        seen_queries.add(q)
        items.append({"query": q, "should_trigger": True})
    for case in triggers.get("negative", []):
        q = case["prompt"]
        if q in seen_queries:
            raise ValueError(
                f"duplicate prompt across triggers cases (case id={case['id']!r}); "
                f"run_eval.py keys results by query string so prompts must be unique"
            )
        seen_queries.add(q)
        items.append({"query": q, "should_trigger": False})
    return items


def _index_by_query(triggers: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Reverse index from prompt back to original case for projection."""
    out: dict[str, dict[str, Any]] = {}
    for case in triggers.get("positive", []):
        out[case["prompt"]] = {**case, "_kind": "positive"}
    for case in triggers.get("negative", []):
        out[case["prompt"]] = {**case, "_kind": "negative"}
    return out


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _aggregate(results: list[dict[str, Any]], threshold: float = 0.5) -> dict[str, float]:
    """Compute precision / recall / F1 over the positive vs negative split.

    A "trigger" decision is per-case: ``trigger_rate >= threshold``.
    Confusion matrix is built across cases (not trials).
    """
    tp = fp = fn = tn = 0
    for r in results:
        triggered = r["trigger_rate"] >= threshold
        if r["should_trigger"]:
            if triggered:
                tp += 1
            else:
                fn += 1
        else:
            if triggered:
                fp += 1
            else:
                tn += 1
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": _f1(precision, recall)}


def _run_eval_py_path(repo_root: Path) -> Path:
    return (
        repo_root / "tools" / "external" / "anthropics-skills"
        / "skills" / "skill-creator" / "scripts" / "run_eval.py"
    )


def _read_pinned_sha(repo_root: Path) -> str:
    p = repo_root / "tools" / "eval-runner" / ".skill-creator-sha"
    return p.read_text(encoding="utf-8").strip() if p.exists() else "unknown"


def _ensure_upstream(repo_root: Path) -> None:
    if not _run_eval_py_path(repo_root).is_file():
        raise FileNotFoundError(
            f"run_eval.py not found at {_run_eval_py_path(repo_root)}. "
            f"Run `make setup-skill-creator` to clone the SHA-pinned upstream."
        )


def invoke_run_eval(
    repo_root: Path,
    skill: str,
    eval_set: list[dict[str, Any]],
    runs: int,
    workers: int,
    timeout: int,
    model: str | None,
) -> dict[str, Any]:
    """Subprocess run_eval.py and return its parsed stdout.

    Caller is responsible for converting from triggers.json shape via
    _to_run_eval_set first.
    """
    _ensure_upstream(repo_root)
    script = _run_eval_py_path(repo_root)
    skill_creator_dir = script.parent.parent  # .../skill-creator/
    skill_path = repo_root / "skills" / skill

    with tempfile.NamedTemporaryFile(
        mode="w", suffix="-eval-set.json", delete=False
    ) as tf:
        json.dump(eval_set, tf)
        eval_set_path = tf.name

    # run_eval.py does `from scripts.utils import parse_skill_md`, so it must
    # be invoked as a package module with the skill-creator directory on
    # PYTHONPATH. Running it as a script (`python /abs/path/run_eval.py`)
    # fails with ModuleNotFoundError. Use `-m` form instead.
    cmd: list[str] = [
        sys.executable,
        "-m", "scripts.run_eval",
        "--eval-set", eval_set_path,
        "--skill-path", str(skill_path),
        "--runs-per-query", str(runs),
        "--num-workers", str(workers),
        "--timeout", str(timeout),
    ]
    if model:
        cmd += ["--model", model]
    env = {**os.environ, "PYTHONPATH": str(skill_creator_dir)}
    # Run from the repo root so find_project_root() in run_eval.py walks up
    # to our .claude/ rather than the upstream clone's tree.
    #
    # stderr is NOT captured: run_eval.py prints per-probe progress there
    # and the loop is long (~20 probes × runs), so swallowing it makes the
    # invocation look like a hang. stdout IS captured — it's a single
    # pretty-printed JSON object we need to parse on success.
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            check=False,
        )
    finally:
        try:
            os.unlink(eval_set_path)
        except FileNotFoundError:
            pass

    if proc.returncode != 0:
        raise RuntimeError(
            f"run_eval.py failed (exit {proc.returncode}); "
            f"stderr was streamed to the terminal above.\n"
            f"stdout:\n{proc.stdout}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"run_eval.py returned non-JSON stdout: {e}\n"
            f"stdout was:\n{proc.stdout[:2000]}"
        ) from e


def project_results(
    triggers: dict[str, Any],
    upstream_output: dict[str, Any],
    runs: int,
    model: str | None,
    upstream_sha: str,
) -> dict[str, Any]:
    """Translate run_eval.py output into our summary shape, with F1 added."""
    by_query = _index_by_query(triggers)
    per_case: list[dict[str, Any]] = []
    for r in upstream_output.get("results", []):
        case = by_query.get(r["query"], {})
        kind = case.get("_kind", "positive" if r["should_trigger"] else "negative")
        actual_load = (
            list(case.get("expected_load", []))
            if r["should_trigger"] and r["pass"]
            else (
                [triggers["skill"]]
                if (not r["should_trigger"]) and (not r["pass"])  # FP: triggered when shouldn't
                else []
            )
        )
        per_case.append(
            {
                "id": case.get("id", "<unknown>"),
                "kind": kind,
                "prompt": r["query"],
                "expected_load": case.get("expected_load", []),
                "must_not_load": case.get("must_not_load", []),
                "trigger_rate": r["trigger_rate"],
                "triggers": r["triggers"],
                "runs": r["runs"],
                "pass": r["pass"],
                "actual_load": actual_load,
            }
        )
    agg = _aggregate(upstream_output.get("results", []))
    return {
        "skill": triggers["skill"],
        "trials_per_case": runs,
        "f1": round(agg["f1"], 4),
        "precision": round(agg["precision"], 4),
        "recall": round(agg["recall"], 4),
        "positive_cases": sum(1 for c in per_case if c["kind"] == "positive"),
        "negative_cases": sum(1 for c in per_case if c["kind"] == "negative"),
        "per_case": per_case,
        "model": {"harness": model or "default"},
        "upstream_sha": upstream_sha,
    }


def run_live(
    repo_root: Path,
    skill: str,
    iteration_dir: Path,
    runs: int,
    workers: int = 5,
    timeout: int = 30,
    model: str | None = None,
) -> dict[str, Any]:
    """End-to-end live run: load → invoke → project → write summary.

    Returns the projected summary dict; caller writes it where it wants.
    Also writes ``iteration-N/triggers/summary.json`` and the upstream's raw
    output for forensics at ``iteration-N/triggers/run_eval_raw.json``.
    """
    triggers = load_triggers(repo_root, skill)
    if triggers is None:
        raise FileNotFoundError(
            f"no triggers.json for skill {skill!r}; "
            f"create skills/{skill}/evals/triggers.json first"
        )
    eval_set = _to_run_eval_set(triggers)
    raw = invoke_run_eval(
        repo_root, skill, eval_set, runs=runs, workers=workers,
        timeout=timeout, model=model,
    )
    summary = project_results(
        triggers, raw, runs=runs, model=model,
        upstream_sha=_read_pinned_sha(repo_root),
    )
    out_dir = iteration_dir / "triggers"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "run_eval_raw.json").write_text(
        json.dumps(raw, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def run_dry(repo_root: Path, skill: str, iteration_dir: Path, trials: int) -> None:
    """Materialize the iteration scaffolding without invoking any model."""
    triggers_dir = iteration_dir / "triggers"
    triggers_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_triggers(repo_root, skill) or {"positive": [], "negative": []}
    placeholder = {
        "skill": skill,
        "trials_per_case": trials,
        "positive": [c["id"] for c in cfg.get("positive", [])],
        "negative": [c["id"] for c in cfg.get("negative", [])],
        "status": "dry-run",
    }
    (triggers_dir / "summary.json").write_text(
        json.dumps(placeholder, indent=2) + "\n", encoding="utf-8"
    )
