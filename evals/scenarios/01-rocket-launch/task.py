"""Scenario 01 — Rocket Launch BPMN deploy + run.

End-to-end: agent designs a small "rocket launch" BPMN and deploys it
via c8ctl. Three scorers in composition cover three failure modes at
three costs:

1. Transcript — did the agent *attempt* ``c8ctl deploy`` at all?
2. Cluster — did the deploy actually land on the cluster?
3. CPT (Phase 2) — does the deployed BPMN behave correctly?

The CPT verifier brings up its own embedded Zeebe and does its own
deploy from the agent's BPMN file (mounted read-only); the cluster
scorer hits the Phase 1 c8run cluster the agent worked against.

Load-bearing skills: camunda-bpmn (design), camunda-process-mgmt
(deploy). Baseline excludes camunda-bpmn (single load-bearing skill —
without-skill arm tests whether the model can produce a deployable
BPMN without the skill's element-template guidance).
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, TaskState, generate, solver

from evals.lib.boot_cluster import boot_cluster
from evals.lib.cluster_assertions import process_deployed_on_cluster
from evals.lib.inspect_transcript import assert_tool_called
from evals.lib.run_cpt import cpt_scorer

METADATA = {
    "skills": ["camunda-bpmn", "camunda-process-mgmt"],
    "image": "with-c8ctl",
    "epochs": 1,
    "tier": "pr",
    "verifier": "composite",
    "baseline": {"mode": "without-skill", "exclude": ["camunda-bpmn"]},
}


@solver
def agent_builds_rocket_launch():
    """Delegates the prompt to the bridged agent."""

    async def solve(state: TaskState, generate_fn: Generate) -> TaskState:
        return await generate_fn(state)

    return solve


@task
def rocket_launch() -> Task:
    return Task(
        dataset=[
            Sample(
                id="happy",
                input=(
                    "Build a BPMN process called `RocketLaunch` that models a "
                    "simple countdown: a start event, a service task "
                    "`PerformCountdown` (job type `countdown`), a service "
                    "task `Liftoff` (job type `liftoff`), and an end event. "
                    "Save it to `/workspace/outputs/process.bpmn` and deploy "
                    "it via c8ctl. Then start one instance with the payload "
                    "`{\"countdownSeconds\": 3}` and report the process "
                    "instance key."
                ),
            ),
            Sample(
                id="edge-missing-service-task",
                input=(
                    "Build a `RocketLaunch` BPMN with just a start event "
                    "wired directly to an end event — no service tasks. "
                    "Save it to `/workspace/outputs/process.bpmn`, deploy "
                    "via c8ctl, and start one instance. (This is the "
                    "minimum-viable shape; verifies you can author and "
                    "deploy without over-engineering.)"
                ),
            ),
        ],
        solver=[
            boot_cluster(),
            agent_builds_rocket_launch(),
            generate(),
        ],
        scorer=[
            assert_tool_called("c8ctl", subcommand="deploy"),
            process_deployed_on_cluster("RocketLaunch"),
            cpt_scorer(),
        ],
        metadata=METADATA,
    )

