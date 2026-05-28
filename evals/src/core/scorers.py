"""Helpers that decorate scorer instances.

``diagnostic()`` marks a scorer's outputs as informational
(non-gating). Inspect still shows the scorer's column on the
dashboard, but ``core.metrics.pass_rate`` and ``scripts.pass_fail``
honor a ``gating=False`` tag in ``Score.metadata`` when deciding
which scores feed the arm-level pass_rate and which ones gate
the per-sample threshold.

Per-instance tagging beats per-scenario lists for two reasons:
the decision lives with the scorer it applies to, and two
instances of the same scorer kind can be marked independently.
"""

from __future__ import annotations

from inspect_ai._util.registry import is_registry_object, registry_info
from inspect_ai.scorer import Score, Scorer, Target
from inspect_ai.solver import TaskState

# Inspect attaches ``__registry_info__`` / ``__registry_params__`` to
# scorers created via the ``@scorer`` decorator. Inspect's
# ``to_scorer`` then accepts anything that's a registered scorer
# object. The diagnostic() wrapper below copies those attributes
# from the inner scorer onto the wrapper so the wrapper is treated
# as the same registered scorer (dashboard column, metric set, name).
_REGISTRY_INFO = "__registry_info__"
_REGISTRY_PARAMS = "__registry_params__"


def diagnostic(inner: Scorer) -> Scorer:
    """Wrap a scorer so its Score outputs carry ``gating=False``.

    The wrapped scorer behaves identically to ``inner`` except that
    every emitted ``Score`` has ``metadata["gating"] = False`` merged
    in. Downstream consumers (regen_baseline, pass_fail) filter on
    this flag to keep diagnostic readings out of the gate. Inspect's
    registry tagging is copied from ``inner`` so the dashboard still
    renders the scorer under its original name.
    """

    async def score(state: TaskState, target: Target) -> Score:
        s = await inner(state, target)
        return Score(
            value=s.value,
            answer=s.answer,
            explanation=s.explanation,
            metadata={**(s.metadata or {}), "gating": False},
        )

    if is_registry_object(inner, type="scorer"):
        # Reuse the inner's registry tag so Inspect treats the wrapper
        # as the same registered scorer. We can't go through
        # ``@scorer`` here because the wrapped instance is per-call,
        # not per-factory.
        setattr(score, _REGISTRY_INFO, registry_info(inner))
        if hasattr(inner, _REGISTRY_PARAMS):
            setattr(score, _REGISTRY_PARAMS, getattr(inner, _REGISTRY_PARAMS))
    return score
