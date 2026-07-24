"""Scorers that check the live cluster the agent worked against via c8ctl.

Answers "did the artifact reach the cluster", distinct from CPT which
tests behaviour against the agent's BPMN in a fresh embedded Zeebe.
"""

from __future__ import annotations

import json

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox


@scorer(metrics=[mean(), stderr()])
def process_deployed_on_cluster(bpmn_process_id: str) -> Scorer:
    """Score 1.0 when a process definition with ``bpmn_process_id`` is
    deployed on the cluster; 0.0 otherwise."""

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        # 60s: the cluster can pause under local contention (30s tripped
        # false timeouts on epochs runs).
        result = await sb.exec(
            ["c8ctl", "list", "pd", "--json"],
            timeout=60,
        )
        if result.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"c8ctl list pd exit {result.returncode}: "
                f"{result.stderr[-500:]}",
            )
        # Exits 0 with empty stdout when the cluster has no process
        # definitions; surface that distinctly from a malformed response.
        if not result.stdout.strip():
            return Score(
                value=0.0,
                explanation=f"{bpmn_process_id} not deployed; cluster has no process definitions",
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return Score(
                value=0.0,
                explanation=f"non-JSON response: {exc}",
                metadata={"raw_stdout": result.stdout[:1000]},
            )

        # c8ctl JSON shape has shifted over versions: bare list,
        # {items: [...]}, or {processDefinitions: [...]}.
        if isinstance(payload, list):
            definitions = payload
        elif isinstance(payload, dict):
            definitions = (
                payload.get("items") or payload.get("processDefinitions") or []
            )
        else:
            definitions = []

        ids = [d.get("Process ID") for d in definitions if isinstance(d, dict)]
        if bpmn_process_id in ids:
            return Score(
                value=1.0,
                explanation=f"{bpmn_process_id} deployed (saw {len(ids)} definition(s))",
                metadata={"deployed_ids": ids},
            )

        # Include the first item's keys to spot a field-name change.
        sample_keys = sorted(definitions[0].keys()) if definitions else []
        return Score(
            value=0.0,
            explanation=(
                f"{bpmn_process_id} not deployed; cluster has {ids} "
                f"(saw {len(definitions)} definition(s), first item keys: {sample_keys})"
            ),
            metadata={
                "deployed_ids": ids,
                "first_item_keys": sample_keys,
                "raw_stdout": result.stdout[:1000],
            },
        )

    return score
