"""Deterministic FEEL scorer: evaluate the agent's expression on the cluster.

The agent saves a FEEL expression to a file; this scorer runs it through
``c8ctl feel evaluate`` (cluster engine, the real Scala FEEL) and checks the
result against an expected value carried in the sample's metadata:

    metadata = {
        "feel_equals": 22,                 # required — expected result
        "feel_vars": {"items": [...]},     # optional — variables
        "feel_path": "/workspace/answer.feel",  # optional — defaults shown
    }

Returns ``None`` (no-op) for samples without ``feel_equals``.
"""

from __future__ import annotations

import json
from typing import Any

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

_DEFAULT_PATH = "/workspace/answer.feel"


def _equal(result: Any, expected: Any) -> bool:
    if isinstance(result, bool) or isinstance(expected, bool):
        return result == expected
    if isinstance(result, (int, float)) and isinstance(expected, (int, float)):
        return abs(result - expected) < 1e-9
    return result == expected


@scorer(metrics=[mean(), stderr()])
def feel_evaluates_to() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score | None:
        if "feel_equals" not in state.metadata:
            return None
        expected = state.metadata["feel_equals"]
        variables = state.metadata.get("feel_vars")
        path = state.metadata.get("feel_path", _DEFAULT_PATH)

        sb = sandbox()
        cat = await sb.exec(["cat", path], timeout=10)
        expr = (cat.stdout or "").strip()
        if cat.returncode != 0 or not expr:
            return Score(value=0.0, explanation=f"no FEEL expression at {path}")

        cmd = ["c8ctl", "feel", "evaluate", expr, "--json"]
        if variables:
            cmd += ["--vars", json.dumps(variables)]
        res = await sb.exec(cmd, timeout=60)
        if res.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"c8ctl feel evaluate exit {res.returncode}: {(res.stderr or '')[-300:]}",
                metadata={"expression": expr},
            )
        try:
            payload = json.loads(res.stdout)
        except json.JSONDecodeError as exc:
            return Score(
                value=0.0,
                explanation=f"non-JSON response: {exc}",
                metadata={"expression": expr, "raw_stdout": (res.stdout or "")[:500]},
            )

        result = payload.get("result")
        ok = _equal(result, expected)
        return Score(
            value=1.0 if ok else 0.0,
            answer=json.dumps(result),
            explanation=f"{expr!r} → {result!r} (expected {expected!r})",
            metadata={
                "expression": expr,
                "result": result,
                "expected": expected,
                "warnings": payload.get("warnings"),
            },
        )

    return score
