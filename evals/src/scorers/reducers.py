"""Custom score reducers for composing outcome scorers.

Inspect's built-in ``at_least(k)`` reducer collapses a list of sub-scores
into a single 0/1 headline, but discards each sub-scorer's explanation
and metadata (it keeps only ``scores[0].metadata`` per the default
``_reduced_score``). When the AND-style headline fires, a reviewer sees
``score=1`` with "(No Explanation)" — they have to drill into the
transcript to learn which sub-scorer did what.

``all_passed`` keeps the AND semantics but builds a rollup string and
per-sub-score metadata so the dashboard's per-sample card carries the
breakdown by name. Names are passed by position because ``Score``
doesn't carry the scorer's name itself, and ``multi_scorer`` runs
sub-scorers in list order.
"""

from __future__ import annotations

from inspect_ai.scorer import Score, ScoreReducer, score_reducer, value_to_float

_to_float = value_to_float()


@score_reducer
def all_passed(names: list[str]) -> ScoreReducer:
    """Reduce sub-scores via AND, preserving per-mode detail.

    Args:
        names: Labels matching the ``scorers=[...]`` list passed to
            ``multi_scorer``, in order. Each label appears in the
            rolled-up explanation and as a metadata key.

    Returns a Score with:
        - ``value`` = 1.0 iff every sub-score's value >= 1.0
        - ``explanation`` = rollup like
          ``"deploy=PASS | lint=PASS | cpt=FAIL: mvn exit 1"``
        - ``metadata["sub_scores"]`` = per-sub-score
          ``{name: {value, explanation, metadata}}`` for drill-in.
    """

    def reduce(scores: list[Score]) -> Score:
        if len(scores) != len(names):
            raise ValueError(
                f"all_passed got {len(scores)} scores but {len(names)} names; "
                "names must mirror multi_scorer's `scorers=[...]` order."
            )

        all_passed_value = all(_to_float(s.value) >= 1.0 for s in scores)

        parts: list[str] = []
        sub_meta: dict[str, dict] = {}
        for name, s in zip(names, scores):
            v = _to_float(s.value)
            status = "PASS" if v >= 1.0 else "FAIL"
            # Tail of the sub-explanation only when it failed — passing
            # scorers' explanations would otherwise bloat the rollup.
            if v < 1.0 and s.explanation:
                # Single line; the per-sample drill-in shows the full
                # transcript when a reviewer wants the full output.
                tail = s.explanation.split("\n", 1)[0][:200]
                parts.append(f"{name}={status}: {tail}")
            else:
                parts.append(f"{name}={status}")
            sub_meta[name] = {
                "value": s.value,
                "explanation": s.explanation,
                "metadata": s.metadata,
            }

        return Score(
            value=1.0 if all_passed_value else 0.0,
            explanation=" | ".join(parts),
            metadata={"sub_scores": sub_meta},
        )

    return reduce
