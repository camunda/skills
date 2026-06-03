"""Shared metric helpers for reading Inspect eval logs.

Used by ``scripts.regenerate_baseline`` to write the outcomes_baseline.json and by
``scripts.pass_fail`` to gate against it. Kept domain-agnostic — no
scenario-specific shaping lives here.
"""

from __future__ import annotations

from pathlib import Path
from statistics import median

from inspect_ai.scorer import value_to_float

from core.paths import SCENARIO_EVALS_DIR, SKILL_EVALS_DIR

# Inspect's own Value→float conversion: letter grades C/P/I map to
# 1.0/0.5/0.0, numbers pass through, and bool / "true" / "false" /
# numeric strings are handled too. Using the framework helper keeps us
# aligned with how ``accuracy()`` scores the same values, instead of
# hand-rolling a letter map.
score_to_float = value_to_float()


def is_gating(score) -> bool:
    """Whether a Score contributes to the gating decision.

    A scorer can mark its Scores non-gating by setting
    ``metadata["gating"] = False`` (e.g. ``assert_skill_loaded`` in its
    diagnostic mode) — those are surfaced for visibility but excluded
    from gating decisions. Scores without the tag default to gating.
    """
    meta = getattr(score, "metadata", None) or {}
    return meta.get("gating", True) is not False


def gating_by_scorer(log) -> dict[str, bool]:
    """Whether each scorer gates, keyed by scorer name.

    Read from raw ``log.samples`` (where every Score keeps its ``metadata``)
    rather than from the reductions: a reducer may drop per-score metadata when
    the epoch values differ, which would silently flip a diagnostic scorer like
    ``assert_skill_loaded`` back to gating. A scorer's gating flag is constant
    across samples, so the first occurrence wins.
    """
    result: dict[str, bool] = {}
    for sample in getattr(log, "samples", None) or []:
        for name, score in (getattr(sample, "scores", None) or {}).items():
            if name not in result:
                result[name] = is_gating(score)
    return result


def reduced_scores(log) -> dict[str, dict[str, float]]:
    """Per-sample ``{scorer: float}`` after epoch reduction, keyed by sample id.

    Reads ``log.reductions`` (one entry per scorer × reducer, each holding the
    epoch-reduced score per sample id) instead of raw ``log.samples`` (one row
    per id×epoch). At epochs=1 the reduction is the identity, so this is correct
    for single- and multi-epoch runs alike. When several reducers are
    configured, ``mean`` wins. Falls back to raw scores if a log predates
    reductions.
    """
    by_scorer: dict[str, object] = {}
    for red in getattr(log, "reductions", None) or []:
        prev = by_scorer.get(red.scorer)
        if prev is None or (
            red.reducer == "mean" and getattr(prev, "reducer", None) != "mean"
        ):
            by_scorer[red.scorer] = red

    out: dict[str, dict[str, float]] = {}
    if by_scorer:
        for scorer, red in by_scorer.items():
            for s in red.samples:
                v = s.value
                out.setdefault(str(s.sample_id), {})[scorer] = (
                    score_to_float(v) if isinstance(v, (int, float, str, bool)) else 0.0
                )
        return out

    # Fallback: no reductions block — treat each raw sample as its own (id at
    # epochs=1 is unique, so this is the identity there too).
    for sample in getattr(log, "samples", None) or []:
        for name, score in (getattr(sample, "scores", None) or {}).items():
            v = getattr(score, "value", None)
            out.setdefault(str(sample.id), {})[name] = (
                score_to_float(v) if isinstance(v, (int, float, str, bool)) else 0.0
            )
    return out


def _usage_field(sample, field: str) -> float:
    """Sum one ModelUsage field across every model a sample touched."""
    usage = getattr(sample, "model_usage", None) or {}
    return float(sum(getattr(u, field, 0) or 0 for u in usage.values()))


def sample_tokens(sample) -> float:
    """Total tokens consumed by a single sample across all models.

    ``total_tokens`` is the all-in figure (input + output + cache read/write);
    it's what the cost baseline gates on, so usage reporting uses it too.
    """
    return _usage_field(sample, "total_tokens")


def sample_turns(sample) -> int:
    """Agent turns = assistant messages (one model generation each)."""
    msgs = getattr(sample, "messages", None) or []
    return sum(1 for m in msgs if getattr(m, "role", None) == "assistant")


def sample_tool_calls(sample) -> int:
    """Total tool invocations the agent made across the sample."""
    msgs = getattr(sample, "messages", None) or []
    return sum(len(getattr(m, "tool_calls", None) or []) for m in msgs)


# Per-sample signals reduced into the baseline. ``tokens`` gates the cost
# ceiling; ``turns`` and ``tool_calls`` are diagnostic — stored so the summary
# can show a delta ("+20% tokens, +2 turns"), never gated.
REDUCED_FIELDS = ("tokens", "turns", "tool_calls")


def reduced_metrics(log) -> dict[str, dict[str, float]]:
    """Per-sample-id ``{tokens, turns, tool_calls}``, each the median across
    epochs. These live on the raw samples (the reduced score carries no usage),
    so we group ``log.samples`` by id and median each — robust to a single
    runaway rollout, and the per-id granularity the cost gate and baseline use.
    At epochs=1 it's just the sample's own values.
    """
    getters = {
        "tokens": sample_tokens,
        "turns": sample_turns,
        "tool_calls": sample_tool_calls,
    }
    by_id: dict[str, dict[str, list[float]]] = {}
    for sample in getattr(log, "samples", None) or []:
        acc = by_id.setdefault(str(sample.id), {f: [] for f in REDUCED_FIELDS})
        for f, fn in getters.items():
            acc[f].append(float(fn(sample)))
    return {
        sid: {f: median(vals) for f, vals in acc.items() if vals}
        for sid, acc in by_id.items()
    }


# Token categories in the order we display them; their sum is the all-in
# total, which prompt caching makes far larger than fresh input + output.
USAGE_FIELDS = (
    "input_tokens",
    "input_tokens_cache_write",
    "input_tokens_cache_read",
    "output_tokens",
)


def token_usage(log) -> dict[str, float]:
    """Per-category token totals across all samples (the keys in USAGE_FIELDS)."""
    samples = getattr(log, "samples", None) or []
    return {f: sum(_usage_field(s, f) for s in samples) for f in USAGE_FIELDS}


def model_id(log) -> str | None:
    """The model id the eval ran against (from the log's eval header)."""
    eval_meta = getattr(log, "eval", None)
    return getattr(eval_meta, "model", None) if eval_meta else None


def sample_duration_s(sample) -> float:
    """Per-sample wall time in seconds."""
    return float(getattr(sample, "total_time", 0) or 0)


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
    for base in (SKILL_EVALS_DIR, SCENARIO_EVALS_DIR):
        d = base / name
        if (d / "outcomes.py").exists():
            return d
    return None


def eval_source_path(name: str, is_trigger: bool = False) -> Path | None:
    """Absolute path to an eval's Python file — ``triggers.py`` for a trigger
    (in ``skills/<skill>/``), else the ``outcomes.py`` under ``skills/`` or
    ``scenarios/``. ``None`` if it doesn't resolve."""
    if is_trigger:
        p = SKILL_EVALS_DIR / name / "triggers.py"
        return p if p.exists() else None
    for base in (SKILL_EVALS_DIR, SCENARIO_EVALS_DIR):
        p = base / name / "outcomes.py"
        if p.exists():
            return p
    return None
