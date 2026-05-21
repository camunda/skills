"""Scenario 00 — c8ctl bootstrap from a clean container.

Exercises the camunda-c8ctl skill's install + first-cluster path
from the ``base`` image (no c8ctl pre-installed). Success = the
agent installs c8ctl, starts a local cluster, and confirms topology.

Verifier: exit-code + JSON-shape check on
``c8ctl get topology --json``. No CPT project needed — the artifact
the skill produces is a working CLI, not a process.
"""

from __future__ import annotations

import json

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Target, scorer
from inspect_ai.solver import Generate, TaskState, generate, solver
from inspect_ai.util import sandbox

METADATA = {
    "skills": ["camunda-c8ctl"],
    "image": "base",
    "epochs": 1,
    "tier": "pr",
    "verifier": "exit-code",
    "baseline": {"mode": "without-skill", "exclude": ["camunda-c8ctl"]},
}


@scorer(metrics=[])
def topology_reachable():
    """Score 1.0 iff ``c8ctl get topology --json`` returns valid JSON
    with at least one broker.
    """

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        result = await sb.exec(["c8ctl", "get", "topology", "--json"], timeout=30)
        if result.returncode != 0:
            return Score(value=0.0, explanation=f"exit {result.returncode}: {result.stderr[-500:]}")
        try:
            topology = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return Score(value=0.0, explanation=f"non-JSON topology: {exc}")
        brokers = topology.get("brokers") or topology.get("Brokers") or []
        if not brokers:
            return Score(value=0.0, explanation=f"no brokers in topology: {topology}")
        return Score(
            value=1.0,
            explanation=f"{len(brokers)} broker(s) reachable",
            metadata={"topology": topology},
        )

    return score


@solver
def agent_solves_bootstrap():
    """Hand the prompt to the bridged agent and let it work."""

    async def solve(state: TaskState, generate_fn: Generate) -> TaskState:
        # In a real run this delegates to Inspect AI's
        # sandbox_agent_bridge(). v1 wires generate() as a stand-in
        # so the scenario file imports cleanly; PR #3 lands the bridge.
        return await generate_fn(state)

    return solve


@task
def c8ctl_bootstrap() -> Task:
    return Task(
        dataset=[
            Sample(
                id="happy",
                input=(
                    "I'm on a fresh Ubuntu container with Node 22 and Java 21 "
                    "installed but no Camunda tooling. Install c8ctl, start a "
                    "local Camunda cluster, and confirm the cluster topology "
                    "is reachable. When you're done, the command "
                    "`c8ctl get topology --json` should return JSON with at "
                    "least one broker."
                ),
            ),
            Sample(
                id="edge-existing-cluster",
                input=(
                    "Same fresh container as before, but I've already got "
                    "c8ctl installed and a cluster running. Verify the "
                    "setup is healthy without restarting anything."
                ),
            ),
        ],
        solver=[agent_solves_bootstrap(), generate()],
        scorer=topology_reachable(),
        metadata=METADATA,
    )
