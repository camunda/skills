"""Solver: confirm the docker-compose Camunda orchestration cluster is reachable.

We use compose (``camunda/camunda``, multi-arch) rather than
``c8ctl cluster start`` (c8run, no aarch64 build).
"""

from __future__ import annotations

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox


@solver
def boot_cluster(timeout_s: int = 60) -> Solver:
    """Confirm topology is reachable; fail fast if not.

    The agent shares orchestration's network namespace
    (``network_mode: "service:orchestration"``), so ``localhost:8080``
    reaches the Camunda REST API directly.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        topology = await sb.exec(
            ["c8ctl", "get", "topology", "--json"], timeout=timeout_s
        )
        if topology.returncode != 0:
            raise RuntimeError(
                f"orchestration unreachable: c8ctl get topology exit "
                f"{topology.returncode}: {topology.stderr[-500:]}"
            )
        state.metadata["topology"] = topology.stdout
        return state

    return solve
