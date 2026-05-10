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
    """Difference between a candidate iteration and the committed baseline.

    Drops are computed as ``baseline - candidate`` so positive means the
    candidate is worse. Drops below ``noise_floor_pp`` are within trial
    noise and should not drive decisions.

    Regression rules are asymmetric — see ``docs/evals.md`` § "How to
    interpret your numbers" for the rationale:

      - **Regression** (PR-blocking): ``with_skill_pass_rate`` drop > 5pp
        (skill made things worse), ``skill_help`` drop > 5pp (skill helps
        less than before), or trigger-eval ``precision`` drop > 5pp
        (over-triggering grew, wasting context).
      - **Warning** (informational): same metrics 2-5pp drop, OR recall
        any drop. Recall is *not* a regression target — for skills
        whose topic is well-covered by training data, low recall just
        means the agent answered fine without help.
      - **Informational only**: trigger F1 itself. F1 is the harmonic
        mean of precision and recall; the components carry the
        decisions, F1 is a summary stat.
    """

    skill: str
    with_skill_pass_rate_drop_pp: float  # positive means current is worse
    skill_help_drop_pp: float  # positive means skill helps less than baseline
    precision_drop_pp: float  # positive means more false-positive triggering
    recall_drop_pp: float  # positive means fewer expected triggers fire
    trigger_f1_drop_pp: float  # informational; not in regression rule
    delta_quality_pp: float  # candidate skill_help, signed
    noise_floor_pp: float
    candidate_summary: dict[str, Any]
    baseline_summary: dict[str, Any]

    @property
    def regression(self) -> bool:
        return (
            self.with_skill_pass_rate_drop_pp > 5.0
            or self.skill_help_drop_pp > 5.0
            or self.precision_drop_pp > 5.0
        )

    @property
    def warning(self) -> bool:
        if self.regression:
            return False
        return (
            self.with_skill_pass_rate_drop_pp > 2.0
            or self.skill_help_drop_pp > 2.0
            or self.precision_drop_pp > 2.0
            or self.recall_drop_pp > self.noise_floor_pp
        )

    def regression_reasons(self) -> list[str]:
        out: list[str] = []
        if self.with_skill_pass_rate_drop_pp > 5.0:
            out.append(
                f"`with_skill` pass rate dropped "
                f"{self.with_skill_pass_rate_drop_pp:.1f}pp (limit 5.0pp)"
            )
        if self.skill_help_drop_pp > 5.0:
            out.append(
                f"`skill_help` (delta vs without_skill) dropped "
                f"{self.skill_help_drop_pp:.1f}pp (limit 5.0pp)"
            )
        if self.precision_drop_pp > 5.0:
            out.append(
                f"trigger precision dropped "
                f"{self.precision_drop_pp:.1f}pp (limit 5.0pp); "
                f"over-triggering grew"
            )
        return out


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
    base_without = float(base_q["without_skill"]["pass_rate"])
    cand_with = float(cand_q.get("with_skill", {}).get("pass_rate", base_with))
    cand_without = float(cand_q.get("without_skill", {}).get("pass_rate", base_without))

    base_f1 = float(base_t["f1"])
    base_precision = float(base_t.get("precision", base_f1))
    base_recall = float(base_t.get("recall", base_f1))
    cand_f1 = float(cand_t.get("f1", base_f1))
    cand_precision = float(cand_t.get("precision", cand_f1))
    cand_recall = float(cand_t.get("recall", cand_f1))

    base_skill_help = base_with - base_without
    cand_skill_help = cand_with - cand_without

    n_cases = int(cand_q.get("with_skill", {}).get("n_cases", 0))
    n_trials = int(cand_q.get("with_skill", {}).get("n_trials", 0))
    if n_cases and n_trials:
        noise = 100.0 / float(n_cases * n_trials)
    else:
        noise = float(baseline.data["regression_thresholds"].get("noise_floor_pp", 0.0))

    return Diff(
        skill=baseline.skill,
        with_skill_pass_rate_drop_pp=(base_with - cand_with) * 100.0,
        skill_help_drop_pp=(base_skill_help - cand_skill_help) * 100.0,
        precision_drop_pp=(base_precision - cand_precision) * 100.0,
        recall_drop_pp=(base_recall - cand_recall) * 100.0,
        trigger_f1_drop_pp=(base_f1 - cand_f1) * 100.0,
        delta_quality_pp=cand_skill_help * 100.0,
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
    """Render a Diff as markdown for posting in a PR comment.

    Lead with ``skill_help`` (delta vs without_skill) since that's the
    headline value the skill is supposed to deliver. Trigger metrics are
    grouped under a "Discovery" section because they're secondary —
    precision matters (over-triggering is always bad), recall is fine to
    drop if quality holds.
    """
    base_q = diff_obj.baseline_summary["quality"]
    base_t = diff_obj.baseline_summary["triggers"]
    cand_q = diff_obj.candidate_summary.get("quality", {})
    cand_t = diff_obj.candidate_summary.get("triggers", {})

    base_with = float(base_q["with_skill"]["pass_rate"])
    base_without = float(base_q["without_skill"]["pass_rate"])
    cand_with = float(cand_q.get("with_skill", {}).get("pass_rate", base_with))
    cand_without = float(cand_q.get("without_skill", {}).get("pass_rate", base_without))

    base_f1 = float(base_t["f1"])
    base_precision = float(base_t.get("precision", base_f1))
    base_recall = float(base_t.get("recall", base_f1))
    cand_f1 = float(cand_t.get("f1", base_f1))
    cand_precision = float(cand_t.get("precision", cand_f1))
    cand_recall = float(cand_t.get("recall", cand_f1))

    base_help = (base_with - base_without) * 100.0
    cand_help = (cand_with - cand_without) * 100.0
    help_delta = cand_help - base_help

    with_delta = (cand_with - base_with) * 100.0
    without_delta = (cand_without - base_without) * 100.0
    f1_delta = (cand_f1 - base_f1) * 100.0
    precision_delta = (cand_precision - base_precision) * 100.0
    recall_delta = (cand_recall - base_recall) * 100.0

    if diff_obj.regression:
        status = "**Status: regression** 🚨"
        reasons = diff_obj.regression_reasons()
        rationale = "; ".join(reasons) if reasons else "see metrics table"
    elif diff_obj.warning:
        status = "**Status: warn** ⚠️"
        rationale = "metrics within 2-5pp of threshold; review before merging"
    else:
        status = "**Status: ok** ✅"
        rationale = "all metrics within thresholds"

    # Quality block — the headline.
    quality_lines = [
        "### Quality (the headline)",
        "",
        "| metric | baseline | candidate | Δ |",
        "|---|---:|---:|---:|",
        f"| **skill_help** (with − without) | {base_help:+.1f}pp | "
        f"{cand_help:+.1f}pp | {_arrow(help_delta)} {_format_pp(help_delta)} |",
        f"| with_skill pass rate | {base_with:.2f} | {cand_with:.2f} | "
        f"{_arrow(with_delta)} {_format_pp(with_delta)} |",
        f"| without_skill pass rate | {base_without:.2f} | {cand_without:.2f} | "
        f"{_arrow(without_delta)} {_format_pp(without_delta)} |",
    ]

    # Discovery block — secondary, but precision drops still regress.
    discovery_lines = [
        "### Discovery (secondary)",
        "",
        "| metric | baseline | candidate | Δ | rule |",
        "|---|---:|---:|---:|---|",
        f"| precision | {base_precision:.2f} | {cand_precision:.2f} | "
        f"{_arrow(precision_delta)} {_format_pp(precision_delta)} | drop >5pp = regression |",
        f"| recall | {base_recall:.2f} | {cand_recall:.2f} | "
        f"{_arrow(recall_delta)} {_format_pp(recall_delta)} | drop = warn only |",
        f"| F1 (informational) | {base_f1:.2f} | {cand_f1:.2f} | "
        f"{_arrow(f1_delta)} {_format_pp(f1_delta)} | derived |",
    ]

    body = [
        f"## {diff_obj.skill} — eval delta",
        "",
        f"{status} — {rationale}.",
        "",
        *quality_lines,
        "",
        *discovery_lines,
        "",
        f"_Noise floor: ±{diff_obj.noise_floor_pp:.1f}pp. "
        f"Drops smaller than this are within trial noise._",
    ]
    return "\n".join(body)
