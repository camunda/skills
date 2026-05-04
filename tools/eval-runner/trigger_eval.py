"""Tier-1 trigger eval: positive + negative probes, F1 over N trials.

Stub: structure and signatures are defined here so cli.py can wire them up.
The skill-creator-driven trial loop and scoring live under Issue #6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TriggerSummary:
    f1: float
    precision: float
    recall: float
    positive_cases: int
    negative_cases: int
    per_case: list[dict[str, Any]]

    def to_json(self) -> dict[str, Any]:
        return {
            "f1": self.f1,
            "precision": self.precision,
            "recall": self.recall,
            "positive_cases": self.positive_cases,
            "negative_cases": self.negative_cases,
            "per_case": self.per_case,
        }


def load_triggers(repo_root: Path, skill: str) -> dict[str, Any] | None:
    p = repo_root / "skills" / skill / "evals" / "triggers.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


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
