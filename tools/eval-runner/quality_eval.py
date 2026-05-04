"""Tier-2 quality eval: paired with_skill / without_skill, LLM-judge + verifiers.

Stub: structure and signatures are defined here so cli.py can wire them up.
The skill-creator wrapper, judge call, and verifier dispatch live under
Issues #7 and #8.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class QualitySummary:
    with_skill_pass_rate: float
    without_skill_pass_rate: float
    n_cases: int
    n_trials: int
    per_case: list[dict[str, Any]]

    @property
    def delta_pp(self) -> float:
        return (self.with_skill_pass_rate - self.without_skill_pass_rate) * 100.0

    def to_json(self) -> dict[str, Any]:
        return {
            "with_skill": {
                "pass_rate": self.with_skill_pass_rate,
                "n_cases": self.n_cases,
                "n_trials": self.n_trials,
            },
            "without_skill": {
                "pass_rate": self.without_skill_pass_rate,
                "n_cases": self.n_cases,
                "n_trials": self.n_trials,
            },
            "delta_pp": self.delta_pp,
            "per_case": self.per_case,
        }


def load_evals(repo_root: Path, skill: str) -> dict[str, Any]:
    p = repo_root / "skills" / skill / "evals" / "evals.json"
    return json.loads(p.read_text(encoding="utf-8"))


def run_dry(repo_root: Path, skill: str, iteration_dir: Path, trials: int) -> None:
    """Materialize the iteration scaffolding without invoking any model."""
    cfg = load_evals(repo_root, skill)
    for arm in ("with_skill", "without_skill"):
        arm_dir = iteration_dir / arm
        arm_dir.mkdir(parents=True, exist_ok=True)
        for case in cfg.get("evals", []):
            (arm_dir / case["id"]).mkdir(parents=True, exist_ok=True)
    placeholder = {
        "skill": skill,
        "trials_per_case": trials,
        "cases": [c["id"] for c in cfg.get("evals", [])],
        "status": "dry-run",
    }
    (iteration_dir / "quality.json").write_text(
        json.dumps(placeholder, indent=2) + "\n", encoding="utf-8"
    )
