"""Scorers that hit the live Phase 1 cluster via c8ctl.

Solvers + scorers share the same sandbox via Inspect AI's ``sandbox()``
handle, so a scorer can poke the c8run cluster the agent was working
against. Use these when "did the artifact reach the cluster" is the
question — distinct from CPT, which spins up a fresh embedded Zeebe in
the verifier sandbox and tests *behaviour* against the agent's BPMN
file.

Compose freely with other scorers (transcript, CPT, judge) by passing
a ``scorer=[...]`` list to ``Task(...)``.
"""

from __future__ import annotations

import json

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox


@scorer(metrics=[])
def process_deployed_on_cluster(bpmn_process_id: str) -> Scorer:
    """Score 1.0 when a process definition with ``bpmn_process_id`` is
    deployed on the cluster the agent worked against; 0.0 otherwise.

    Uses ``c8ctl get process-definition --json``. The agent's deploy
    may have created multiple versions; we only check existence, not
    version count.
    """

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        result = await sb.exec(
            ["c8ctl", "get", "process-definition", "--json"],
            timeout=30,
        )
        if result.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"c8ctl get process-definition exit {result.returncode}: "
                f"{result.stderr[-500:]}",
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return Score(value=0.0, explanation=f"non-JSON response: {exc}")

        definitions = payload if isinstance(payload, list) else payload.get("items", [])
        ids = [
            d.get("bpmnProcessId") or d.get("processDefinitionId")
            for d in definitions
            if isinstance(d, dict)
        ]
        if bpmn_process_id in ids:
            return Score(
                value=1.0,
                explanation=f"{bpmn_process_id} deployed (saw {len(ids)} definition(s))",
                metadata={"deployed_ids": ids},
            )
        return Score(
            value=0.0,
            explanation=f"{bpmn_process_id} not deployed; cluster has {ids}",
            metadata={"deployed_ids": ids},
        )

    return score
