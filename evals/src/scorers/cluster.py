"""Scorers that hit the live Phase 1 cluster via c8ctl.

Solvers + scorers share the same sandbox via Inspect AI's ``sandbox()``
handle, so a scorer can poke the Camunda cluster the agent was working
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

# Field names where a process definition's BPMN id might live.
# c8ctl emits human-readable column headers for `list pd --json`:
# `"Process ID"` (with a space). Older / underlying shapes used
# `bpmnProcessId` etc.; keep them so this works across versions.
_PROCESS_ID_KEYS = (
    "Process ID",
    "bpmnProcessId",
    "processDefinitionId",
    "bpmn_process_id",
    "processId",
)


def _extract_process_id(definition: dict) -> str | None:
    for key in _PROCESS_ID_KEYS:
        value = definition.get(key)
        if isinstance(value, str) and value:
            return value
    return None


@scorer(metrics=[])
def process_deployed_on_cluster(bpmn_process_id: str) -> Scorer:
    """Score 1.0 when a process definition with ``bpmn_process_id`` is
    deployed on the cluster the agent worked against; 0.0 otherwise.

    Uses ``c8ctl list pd --json`` (``pd`` = process-definition). On a
    miss, the explanation includes the raw response keys so the next
    iteration can pinpoint a c8ctl output-shape change.
    """

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        result = await sb.exec(
            ["c8ctl", "list", "pd", "--json"],
            timeout=30,
        )
        if result.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"c8ctl list pd exit {result.returncode}: "
                f"{result.stderr[-500:]}",
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return Score(
                value=0.0,
                explanation=f"non-JSON response: {exc}",
                metadata={"raw_stdout": result.stdout[:1000]},
            )

        # c8ctl JSON output has shifted shapes over versions: a bare
        # list, {items: [...]}, or {processDefinitions: [...]}. Try
        # them in order.
        if isinstance(payload, list):
            definitions = payload
        elif isinstance(payload, dict):
            definitions = (
                payload.get("items")
                or payload.get("processDefinitions")
                or []
            )
        else:
            definitions = []

        ids = [_extract_process_id(d) for d in definitions if isinstance(d, dict)]
        if bpmn_process_id in ids:
            return Score(
                value=1.0,
                explanation=f"{bpmn_process_id} deployed (saw {len(ids)} definition(s))",
                metadata={"deployed_ids": ids},
            )

        # Diagnostic: include the first item's keys so we can spot a
        # field-name change on the next run.
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
