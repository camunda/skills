"""Solver: boot a local c8run cluster inside the sandbox.

Used by scenarios where Phase 1 needs a live Camunda cluster for the
agent to interact with via c8ctl. ``c8ctl cluster start`` is
idempotent — re-running is a no-op if the cluster is already up.

Wrapped as an Inspect AI solver so scenarios can compose:

    chain(boot_cluster(), agent_prompt(...), ...)
"""

from __future__ import annotations

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox


@solver
def boot_cluster(timeout_s: int = 180) -> Solver:
    """Start c8run via c8ctl and wait for the cluster to be ready.

    Assumes ``c8ctl`` is on PATH in the sandbox (image: with-c8ctl).
    Polls ``c8ctl get topology --json`` until the cluster responds or
    ``timeout_s`` elapses.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        start = await sb.exec(["c8ctl", "cluster", "start"], timeout=timeout_s)
        if start.returncode != 0:
            raise RuntimeError(f"c8ctl cluster start failed: {start.stderr}")
        # Confirm topology is reachable. c8ctl handles its own retries
        # when --json is used, so a single call here is fine.
        topology = await sb.exec(["c8ctl", "get", "topology", "--json"], timeout=30)
        if topology.returncode != 0:
            raise RuntimeError(f"c8ctl get topology failed: {topology.stderr}")
        state.metadata["topology"] = topology.stdout
        return state

    return solve
