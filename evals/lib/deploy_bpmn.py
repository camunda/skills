"""Solver: deploy a BPMN file produced by the agent.

Reads from a known output path (``/workspace/outputs/process.bpmn``
by default) and deploys via ``c8ctl deploy``. Stashes the deployment
key on ``state.metadata`` for downstream solvers / scorers.
"""

from __future__ import annotations

import json

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox


@solver
def deploy_bpmn(path: str = "/workspace/outputs/process.bpmn") -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sb = sandbox()
        exists = await sb.exec(["test", "-f", path])
        if exists.returncode != 0:
            state.metadata["deploy_error"] = f"missing artifact: {path}"
            return state
        result = await sb.exec(["c8ctl", "deploy", "--json", path], timeout=60)
        state.metadata["deploy_stdout"] = result.stdout
        state.metadata["deploy_stderr"] = result.stderr
        state.metadata["deploy_returncode"] = result.returncode
        if result.returncode == 0:
            try:
                state.metadata["deploy"] = json.loads(result.stdout)
            except json.JSONDecodeError:
                pass
        return state

    return solve
