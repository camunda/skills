"""Load, validate, and diff baseline.json files for a skill.

Schema lives in tools/skill-lint/schemas/baseline.schema.json so a single
source of truth covers both lint-time validation and runtime loading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_VERSION = 1


def _schema_path() -> Path:
    here = Path(__file__).resolve()
    return here.parent.parent / "skill-lint" / "schemas" / "baseline.schema.json"


def _load_schema() -> dict[str, Any]:
    return json.loads(_schema_path().read_text(encoding="utf-8"))


@dataclass
class Baseline:
    path: Path
    data: dict[str, Any]

    @property
    def skill(self) -> str:
        return self.data["skill"]

    @property
    def with_skill_pass_rate(self) -> float:
        return float(self.data["quality"]["with_skill"]["pass_rate"])

    @property
    def trigger_f1(self) -> float:
        return float(self.data["triggers"]["f1"])


def baseline_path(repo_root: Path, skill: str) -> Path:
    return repo_root / "skills" / skill / "evals" / "baseline.json"


def load(repo_root: Path, skill: str) -> Baseline | None:
    """Return the committed baseline for ``skill`` or None if absent."""
    p = baseline_path(repo_root, skill)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"{p}: unsupported schema_version {data.get('schema_version')!r} "
            f"(expected {SCHEMA_VERSION})"
        )
    validate(data)
    return Baseline(path=p, data=data)


def validate(data: dict[str, Any]) -> None:
    """Raise if ``data`` does not conform to the baseline schema."""
    validator = Draft202012Validator(_load_schema())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        msgs = [f"/{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors]
        raise ValueError("baseline schema violations:\n  " + "\n  ".join(msgs))


@dataclass
class Diff:
    """Difference between a candidate iteration and the committed baseline."""

    skill: str
    with_skill_pass_rate_drop_pp: float  # positive means current is worse
    trigger_f1_drop_pp: float  # positive means current is worse
    delta_quality_pp: float  # signed: with_skill - without_skill, candidate
    noise_floor_pp: float
    candidate_summary: dict[str, Any]
    baseline_summary: dict[str, Any]

    @property
    def regression(self) -> bool:
        return (
            self.with_skill_pass_rate_drop_pp > 5.0
            or self.trigger_f1_drop_pp > 5.0
        )

    @property
    def warning(self) -> bool:
        return (
            self.with_skill_pass_rate_drop_pp > 2.0
            or self.trigger_f1_drop_pp > 2.0
        )


def diff(baseline: Baseline, candidate: dict[str, Any]) -> Diff:
    """Compare a candidate summary.json shape against the committed baseline.

    ``candidate`` follows the same nested shape as baseline.json's
    ``triggers`` and ``quality`` sub-objects (this matches what the runner
    writes to summary.json).
    """
    base_q = baseline.data["quality"]
    base_t = baseline.data["triggers"]
    cand_q = candidate.get("quality", {})
    cand_t = candidate.get("triggers", {})

    base_with = float(base_q["with_skill"]["pass_rate"])
    cand_with = float(cand_q.get("with_skill", {}).get("pass_rate", base_with))

    base_f1 = float(base_t["f1"])
    cand_f1 = float(cand_t.get("f1", base_f1))

    cand_without = float(cand_q.get("without_skill", {}).get("pass_rate", 0.0))
    delta_quality_pp = (cand_with - cand_without) * 100.0

    n_cases = int(cand_q.get("with_skill", {}).get("n_cases", 0))
    n_trials = int(cand_q.get("with_skill", {}).get("n_trials", 0))
    if n_cases and n_trials:
        noise = 100.0 / float(n_cases * n_trials)
    else:
        noise = float(baseline.data["regression_thresholds"].get("noise_floor_pp", 0.0))

    return Diff(
        skill=baseline.skill,
        with_skill_pass_rate_drop_pp=(base_with - cand_with) * 100.0,
        trigger_f1_drop_pp=(base_f1 - cand_f1) * 100.0,
        delta_quality_pp=delta_quality_pp,
        noise_floor_pp=noise,
        candidate_summary=candidate,
        baseline_summary=baseline.data,
    )
