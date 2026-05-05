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


# --- Markdown rendering for PR comments ------------------------------------


def _arrow(delta_pp: float) -> str:
    """Unicode arrow indicating direction. Positive = improvement vs baseline."""
    if delta_pp > 0.05:
        return "▲"
    if delta_pp < -0.05:
        return "▼"
    return "≈"


def _format_pp(value: float) -> str:
    return f"{value:+.1f}pp"


def render_markdown(diff_obj: Diff) -> str:
    """Render a Diff as markdown suitable for posting in a PR comment.

    Example output:

        ## camunda-feel — eval delta

        | metric | baseline | candidate | Δ |
        |---|---:|---:|---:|
        | trigger F1 | 0.91 | 0.86 | ▼ -5.0pp |
        | with_skill pass rate | 0.88 | 0.82 | ▼ -6.0pp |
        | without_skill pass rate | 0.42 | 0.40 | ≈ -2.0pp |
        | with−without delta | 46.0pp | 42.0pp | — |

        **Status: regression** — `with_skill_pass_rate` dropped 6.0pp (limit 5.0pp).

        Noise floor: ±2.5pp. Drops smaller than this are within trial noise.
    """
    base_q = diff_obj.baseline_summary["quality"]
    base_t = diff_obj.baseline_summary["triggers"]
    cand_q = diff_obj.candidate_summary.get("quality", {})
    cand_t = diff_obj.candidate_summary.get("triggers", {})

    base_with = float(base_q["with_skill"]["pass_rate"])
    base_without = float(base_q["without_skill"]["pass_rate"])
    base_f1 = float(base_t["f1"])
    cand_with = float(cand_q.get("with_skill", {}).get("pass_rate", base_with))
    cand_without = float(cand_q.get("without_skill", {}).get("pass_rate", base_without))
    cand_f1 = float(cand_t.get("f1", base_f1))

    f1_delta = (cand_f1 - base_f1) * 100.0
    with_delta = (cand_with - base_with) * 100.0
    without_delta = (cand_without - base_without) * 100.0

    base_delta_q = (base_with - base_without) * 100.0
    cand_delta_q = (cand_with - cand_without) * 100.0

    if diff_obj.regression:
        status = "**Status: regression** 🚨"
        rationale_bits: list[str] = []
        if diff_obj.with_skill_pass_rate_drop_pp > 5.0:
            rationale_bits.append(
                f"`with_skill` dropped {diff_obj.with_skill_pass_rate_drop_pp:.1f}pp "
                f"(limit 5.0pp)"
            )
        if diff_obj.trigger_f1_drop_pp > 5.0:
            rationale_bits.append(
                f"trigger F1 dropped {diff_obj.trigger_f1_drop_pp:.1f}pp "
                f"(limit 5.0pp)"
            )
        rationale = "; ".join(rationale_bits) or "see metrics table"
    elif diff_obj.warning:
        status = "**Status: warn** ⚠️"
        rationale = "drops above 2pp but below 5pp regression threshold"
    else:
        status = "**Status: ok** ✅"
        rationale = "all metrics within thresholds"

    rows = [
        ("trigger F1", base_f1, cand_f1, f1_delta),
        ("with_skill pass rate", base_with, cand_with, with_delta),
        ("without_skill pass rate", base_without, cand_without, without_delta),
    ]
    table_lines = [
        "| metric | baseline | candidate | Δ |",
        "|---|---:|---:|---:|",
    ]
    for label, b, c, d in rows:
        table_lines.append(
            f"| {label} | {b:.2f} | {c:.2f} | {_arrow(d)} {_format_pp(d)} |"
        )
    table_lines.append(
        f"| with−without delta | {base_delta_q:.1f}pp | {cand_delta_q:.1f}pp | "
        f"{_arrow(cand_delta_q - base_delta_q)} {_format_pp(cand_delta_q - base_delta_q)} |"
    )

    body = [
        f"## {diff_obj.skill} — eval delta",
        "",
        *table_lines,
        "",
        f"{status} — {rationale}.",
        "",
        f"_Noise floor: ±{diff_obj.noise_floor_pp:.1f}pp. "
        f"Drops smaller than this are within trial noise._",
    ]
    return "\n".join(body)
