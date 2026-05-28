"""Shared metric helpers for reading Inspect eval logs.

Used by ``scripts.regen_baseline`` to write the baseline.json and by
``scripts.pass_fail`` to gate against it. Kept domain-agnostic — no
scenario-specific shaping lives here.
"""

from __future__ import annotations

# Inspect's letter-grade scorers (model_graded_qa, model_graded_fact)
# emit "C" / "P" / "I" as the raw per-sample score; the accuracy()
# metric converts to 1.0 / 0.5 / 0.0. Mirror that here so callers
# can mix numeric scorers (mean) with letter scorers (accuracy)
# without conditional-casting at every site.
_LETTER_TO_FLOAT = {"C": 1.0, "P": 0.5, "I": 0.0}


def is_gating(score) -> bool:
    """Whether a Score contributes to the gating pass_rate.

    Scores wrapped via ``core.scorers.diagnostic()`` carry
    ``metadata["gating"] = False`` — those are surfaced for visibility
    but excluded from gating decisions. Scores without the tag default
    to gating.
    """
    meta = getattr(score, "metadata", None) or {}
    return meta.get("gating", True) is not False


def pass_rate(log) -> float:
    """Mean of gating per-scorer values across all samples.

    For a multi-scorer task (e.g. rocket-launch with cluster + lint +
    CPT, or dev-routing with skill-load + model_graded_qa), this
    averages every gating scorer's value across every sample —
    diagnostic scorers (tagged via ``core.scorers.diagnostic()``) are
    skipped so the arm-level pass_rate reflects only the metrics
    that actually gate the eval.
    """
    samples = getattr(log, "samples", None) or []
    values: list[float] = []
    for sample in samples:
        scores = getattr(sample, "scores", None) or {}
        for score in scores.values():
            if not is_gating(score):
                continue
            v = getattr(score, "value", None)
            if isinstance(v, (int, float)):
                values.append(float(v))
            elif isinstance(v, str) and v.upper() in _LETTER_TO_FLOAT:
                values.append(_LETTER_TO_FLOAT[v.upper()])
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
    """Resolve the scenario directory name from the log's task name.

    Inspect task names are snake_case (``dev_routing``); scenario
    directories are kebab-case (``dev-routing``). Map by replacing
    underscores. Returns ``None`` if the log lacks a task name.
    """
    eval_meta = getattr(log, "eval", None)
    if eval_meta is None:
        return None
    task = getattr(eval_meta, "task", None)
    return task.replace("_", "-") if task else None
