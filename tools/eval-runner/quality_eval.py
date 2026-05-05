"""Tier-2 quality eval: paired with_skill / without_skill, LLM-judge.

Per (case × arm × trial), runs the agent via ``sdk_runner.run_arm`` and the
grader via ``sdk_runner.run_grader``. Aggregates per-case + aggregate pass
rates and writes a ``summary.json`` matching the baseline schema.

Pass criterion (per trial): grader's ``summary.pass_rate >= QUALITY_PASS_THRESHOLD``.
A case "passes" if the majority of its trials pass — more nuanced aggregation
is left to follow-up if it proves needed.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sdk_runner

QUALITY_PASS_THRESHOLD = 0.5
DEFAULT_HARNESS_MODEL = "claude-opus-4-7"
DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"


# --- Shapes -----------------------------------------------------------------


@dataclass
class TrialOutcome:
    arm: str
    case_id: str
    trial: int
    passed: bool
    grading_pass_rate: float
    cost_usd: float | None
    duration_ms: int
    skill_loads_via_tool: list[str]
    skill_loads_via_read: list[str]


@dataclass
class CaseAggregate:
    id: str
    with_skill_pass_rate: float
    without_skill_pass_rate: float
    trials: list[TrialOutcome] = field(default_factory=list)


# --- I/O --------------------------------------------------------------------


def load_evals(repo_root: Path, skill: str) -> dict[str, Any]:
    p = repo_root / "skills" / skill / "evals" / "evals.json"
    return json.loads(p.read_text(encoding="utf-8"))


def case_dir(iteration_dir: Path, arm: str, case_id: str, trial: int) -> Path:
    return iteration_dir / arm / case_id / f"trial-{trial}"


# --- Orchestration ---------------------------------------------------------


async def _run_one_trial(
    *,
    repo_root: Path,
    iteration_dir: Path,
    skill: str,
    case: dict[str, Any],
    arm: str,
    trial: int,
    harness_model: str,
    judge_model: str,
    arm_max_budget_usd: float | None,
    grader_max_budget_usd: float | None,
) -> TrialOutcome:
    cdir = case_dir(iteration_dir, arm, case["id"], trial)
    cdir.mkdir(parents=True, exist_ok=True)
    outputs = cdir / "outputs"
    transcript = cdir / "transcript.jsonl"

    # Persist the case prompt for the report.
    (cdir / "eval_metadata.json").write_text(
        json.dumps(
            {"eval_name": case["id"], "prompt": case["prompt"],
             "arm": arm, "trial": trial},
            indent=2,
        ),
        encoding="utf-8",
    )

    arm_result = await sdk_runner.run_arm(
        repo_root=repo_root,
        prompt=case["prompt"],
        target_skill=skill,
        arm=arm,
        case_id=case["id"],
        trial=trial,
        outputs_dir=outputs,
        transcript_path=transcript,
        model=harness_model,
        max_budget_usd=arm_max_budget_usd,
    )
    (cdir / "timing.json").write_text(
        json.dumps(arm_result.to_timing_json(), indent=2),
        encoding="utf-8",
    )
    (cdir / "tool_uses.json").write_text(
        json.dumps(
            {
                "tool_uses": arm_result.tool_uses,
                "skill_loads": {
                    "via_skill_tool": arm_result.skill_loads_via_tool,
                    "via_read": arm_result.skill_loads_via_read,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    grading: dict[str, Any] = {}
    grading_pass_rate = 0.0
    try:
        grading = await sdk_runner.run_grader(
            repo_root=repo_root,
            expectations=case.get("expectations", []),
            transcript_path=transcript,
            outputs_dir=outputs,
            case_dir=cdir,
            judge_model=judge_model,
            max_budget_usd=grader_max_budget_usd,
        )
        grading_pass_rate = float(
            grading.get("summary", {}).get("pass_rate", 0.0)
        )
    except Exception as e:  # noqa: BLE001 - surface but don't crash the run
        (cdir / "grading_error.txt").write_text(str(e), encoding="utf-8")

    return TrialOutcome(
        arm=arm,
        case_id=case["id"],
        trial=trial,
        passed=grading_pass_rate >= QUALITY_PASS_THRESHOLD,
        grading_pass_rate=grading_pass_rate,
        cost_usd=arm_result.cost_usd,
        duration_ms=arm_result.duration_ms,
        skill_loads_via_tool=arm_result.skill_loads_via_tool,
        skill_loads_via_read=arm_result.skill_loads_via_read,
    )


async def _run_all(
    *,
    repo_root: Path,
    iteration_dir: Path,
    skill: str,
    cases: list[dict[str, Any]],
    trials: int,
    harness_model: str,
    judge_model: str,
    arm_max_budget_usd: float | None,
    grader_max_budget_usd: float | None,
    concurrency: int,
) -> list[TrialOutcome]:
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(coro: Awaitable[TrialOutcome]) -> TrialOutcome:
        async with semaphore:
            return await coro

    coros = []
    for case in cases:
        for arm in ("with_skill", "without_skill"):
            for trial in range(1, trials + 1):
                coros.append(
                    _bounded(
                        _run_one_trial(
                            repo_root=repo_root,
                            iteration_dir=iteration_dir,
                            skill=skill,
                            case=case,
                            arm=arm,
                            trial=trial,
                            harness_model=harness_model,
                            judge_model=judge_model,
                            arm_max_budget_usd=arm_max_budget_usd,
                            grader_max_budget_usd=grader_max_budget_usd,
                        )
                    )
                )
    return list(await asyncio.gather(*coros))


# --- Aggregation ------------------------------------------------------------


def aggregate(trials: list[TrialOutcome]) -> dict[str, Any]:
    by_case: dict[str, list[TrialOutcome]] = {}
    for t in trials:
        by_case.setdefault(t.case_id, []).append(t)

    per_case = []
    with_skill_rates: list[float] = []
    without_skill_rates: list[float] = []
    total_cost: float = 0.0
    n_cases = len(by_case)
    n_trials_per_case = (
        max((len([t for t in ts if t.arm == "with_skill"]) for ts in by_case.values()), default=0)
    )

    for case_id, ts in sorted(by_case.items()):
        with_arm = [t for t in ts if t.arm == "with_skill"]
        without_arm = [t for t in ts if t.arm == "without_skill"]
        w_rate = (
            statistics.mean(1.0 if t.passed else 0.0 for t in with_arm)
            if with_arm else 0.0
        )
        wo_rate = (
            statistics.mean(1.0 if t.passed else 0.0 for t in without_arm)
            if without_arm else 0.0
        )
        with_skill_rates.append(w_rate)
        without_skill_rates.append(wo_rate)
        for t in ts:
            if t.cost_usd:
                total_cost += t.cost_usd
        per_case.append(
            {"id": case_id, "with_skill": round(w_rate, 4),
             "without_skill": round(wo_rate, 4)}
        )

    with_avg = (
        statistics.mean(with_skill_rates) if with_skill_rates else 0.0
    )
    without_avg = (
        statistics.mean(without_skill_rates) if without_skill_rates else 0.0
    )
    return {
        "with_skill": {
            "pass_rate": round(with_avg, 4),
            "n_cases": n_cases,
            "n_trials": n_trials_per_case,
        },
        "without_skill": {
            "pass_rate": round(without_avg, 4),
            "n_cases": n_cases,
            "n_trials": n_trials_per_case,
        },
        "delta_pp": round((with_avg - without_avg) * 100.0, 2),
        "per_case": per_case,
        "estimated_cost_usd": round(total_cost, 4),
    }


# --- Public entry points ----------------------------------------------------


def run_live(
    *,
    repo_root: Path,
    skill: str,
    iteration_dir: Path,
    trials: int = 3,
    harness_model: str = DEFAULT_HARNESS_MODEL,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    arm_max_budget_usd: float | None = 1.0,
    grader_max_budget_usd: float | None = 0.5,
    concurrency: int = 4,
) -> dict[str, Any]:
    """End-to-end live quality run. Writes per-trial files + summary.json."""
    evals = load_evals(repo_root, skill)
    cases = evals.get("evals", [])
    if not cases:
        raise ValueError(f"no eval cases for skill {skill!r}")

    iteration_dir.mkdir(parents=True, exist_ok=True)

    trial_outcomes = asyncio.run(
        _run_all(
            repo_root=repo_root,
            iteration_dir=iteration_dir,
            skill=skill,
            cases=cases,
            trials=trials,
            harness_model=harness_model,
            judge_model=judge_model,
            arm_max_budget_usd=arm_max_budget_usd,
            grader_max_budget_usd=grader_max_budget_usd,
            concurrency=concurrency,
        )
    )

    quality = aggregate(trial_outcomes)
    summary = {
        "skill": skill,
        "iteration": iteration_dir.name,
        "trials_per_case": trials,
        "model": {
            "provider": "anthropic",
            "id": harness_model,
            "harness": "claude-agent-sdk",
            "judge": judge_model,
        },
        "quality": quality,
        "trials": [
            {
                "arm": t.arm, "case_id": t.case_id, "trial": t.trial,
                "passed": t.passed, "grading_pass_rate": t.grading_pass_rate,
                "cost_usd": t.cost_usd, "duration_ms": t.duration_ms,
                "skill_loads": {
                    "via_skill_tool": t.skill_loads_via_tool,
                    "via_read": t.skill_loads_via_read,
                },
            }
            for t in trial_outcomes
        ],
    }
    return summary


def run_dry(repo_root: Path, skill: str, iteration_dir: Path, trials: int) -> None:
    """Materialize the iteration scaffolding without invoking any model."""
    evals = load_evals(repo_root, skill)
    for arm in ("with_skill", "without_skill"):
        arm_dir = iteration_dir / arm
        arm_dir.mkdir(parents=True, exist_ok=True)
        for case in evals.get("evals", []):
            (arm_dir / case["id"]).mkdir(parents=True, exist_ok=True)
    placeholder = {
        "skill": skill,
        "trials_per_case": trials,
        "cases": [c["id"] for c in evals.get("evals", [])],
        "status": "dry-run",
    }
    (iteration_dir / "quality.json").write_text(
        json.dumps(placeholder, indent=2) + "\n", encoding="utf-8"
    )
