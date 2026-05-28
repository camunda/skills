"""Solver: confirm the Camunda orchestration cluster is reachable.

The cluster is provisioned by docker compose (``compose-*.yaml``'s
``orchestration`` service running ``camunda/camunda:8.9`` with H2 — no
external Elasticsearch / Postgres). Compose's
``depends_on: condition: service_healthy`` gates the agent container
on the orchestration healthcheck, so by the time this solver runs the
cluster is up; we just confirm with a topology query.

We don't use ``c8ctl cluster start`` (c8run-based) — c8run has no
aarch64 build and ``camunda/camunda`` is multi-arch, so compose is
the portable path.

Scenarios that test the install path itself (c8ctl-bootstrap) should
skip this solver — they exercise ``c8ctl get topology`` as part of
the agent's own work.
"""

from __future__ import annotations

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox


@solver
def boot_cluster(timeout_s: int = 60) -> Solver:
    """Confirm topology is reachable; fail fast if not.

    The agent's container shares orchestration's network namespace
    (``network_mode: "service:orchestration"`` in the compose file),
    so ``localhost:8080`` in the agent reaches the Camunda REST API
    directly — no profile setup needed.

    Assumes ``c8ctl`` is on PATH in the sandbox (image: with-c8ctl).
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
