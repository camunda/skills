"""Shared metric helpers for reading Inspect eval logs.

Used by ``scripts.regen_baseline`` to write the outcomes_baseline.json and by
``scripts.pass_fail`` to gate against it. Kept domain-agnostic — no
scenario-specific shaping lives here.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai.scorer import value_to_float

from core.paths import SCENARIOS_DIR, SKILL_EVALS_DIR

# Inspect's own Value→float conversion: letter grades C/P/I map to
# 1.0/0.5/0.0, numbers pass through, and bool / "true" / "false" /
# numeric strings are handled too. Using the framework helper keeps us
# aligned with how ``accuracy()`` scores the same values, instead of
# hand-rolling a letter map.
score_to_float = value_to_float()


def is_gating(score) -> bool:
    """Whether a Score contributes to the gating pass_rate.

    A scorer can mark its Scores non-gating by setting
    ``metadata["gating"] = False`` (e.g. ``assert_skill_loaded`` in its
    diagnostic mode) — those are surfaced for visibility but excluded
    from gating decisions. Scores without the tag default to gating.
    """
    meta = getattr(score, "metadata", None) or {}
    return meta.get("gating", True) is not False


def pass_rate(log) -> float:
    """Mean of gating per-scorer values across all samples.

    For a multi-scorer task (e.g. rocket-launch with cluster + lint +
    CPT, or dev-routing with skill-load + model_graded_qa), this
    averages every gating scorer's value across every sample —
    non-gating scorers (``metadata["gating"] = False``) are skipped so
    the arm-level pass_rate reflects only the metrics that actually
    gate the eval.
    """
    samples = getattr(log, "samples", None) or []
    values: list[float] = []
    for sample in samples:
        scores = getattr(sample, "scores", None) or {}
        for score in scores.values():
            if not is_gating(score):
                continue
            v = getattr(score, "value", None)
            if isinstance(v, (int, float, str, bool)):
                values.append(score_to_float(v))
    return sum(values) / len(values) if values else 0.0


def sample_tokens(sample) -> float:
    """Total tokens consumed by a single sample across all models."""
    usage = getattr(sample, "model_usage", None) or {}
    return float(sum(getattr(u, "total_tokens", 0) or 0 for u in usage.values()))


def sample_duration_s(sample) -> float:
    """Per-sample wall time in seconds."""
    return float(getattr(sample, "total_time", 0) or 0)


def total_tokens(log) -> float:
    """Sum total_tokens across all samples (and every model)."""
    samples = getattr(log, "samples", None) or []
    return sum(sample_tokens(s) for s in samples)


def duration_s(log) -> float:
    """Mean per-sample wall time (seconds).

    Inspect tracks duration per sample, not on the log-level stats
    object. With ``max_samples=1`` this is just the run's wall time;
    with parallel samples it's the average — note that the arm-level
    wall clock is bounded by the SLOWEST sample, not the sum.
    """
    samples = getattr(log, "samples", None) or []
    if not samples:
        return 0.0
    return sum(sample_duration_s(s) for s in samples) / len(samples)


def task_arg(log, name: str, default: str | None = None) -> str | None:
    """Read a task argument (``-T <name>=<value>``) from the eval log."""
    eval_meta = getattr(log, "eval", None)
    if eval_meta is None:
        return default
    args = getattr(eval_meta, "task_args", None) or {}
    return args.get(name, default)


def scenario_id(log) -> str | None:
    """The eval's display name: the log's task name, kebab-cased.

    Inspect task names are snake_case (``camunda_feel``); the on-disk
    directory is kebab-case (``camunda-feel``). Returns ``None`` if the
    log lacks a task name.
    """
    eval_meta = getattr(log, "eval", None)
    if eval_meta is None:
        return None
    task = getattr(eval_meta, "task", None)
    return task.replace("_", "-") if task else None


def baseline_dir(name: str | None) -> Path | None:
    """The directory holding ``outcomes_baseline.json`` for an eval ``name``.

    Outcome evals live in ``skills/<skill>/`` (single-skill) or
    ``scenarios/<id>/`` (cross-skill). Triggers (eval name ``trigger-<skill>``)
    match neither and return ``None`` — they have no token baseline.
    """
    if not name:
        return None
    for base in (SKILL_EVALS_DIR, SCENARIOS_DIR):
        d = base / name
        if (d / "outcomes.py").exists():
            return d
    return None
