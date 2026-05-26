"""Rocket Launch BPMN deploy + run.

End-to-end: agent designs a small "rocket launch" BPMN and deploys it
to a running Camunda 8.9 cluster (provisioned by docker compose).
Three scorers compose to cover three failure modes at three costs:

1. Transcript — did the agent *attempt* ``c8ctl deploy`` at all?
2. Cluster — did the deploy actually land on the cluster?
3. CPT — does the deployed process actually run to completion?

The CPT verifier runs in **remote runtime mode** against the same
orchestration cluster the agent worked against (shared via
``network_mode: service:orchestration``). It starts a process
instance against the agent's already-deployed process and asserts it
completes. The prompt asks for a self-contained BPMN (timers, no
external workers), so the verifier doesn't need to mock anything.

Load-bearing skills: camunda-bpmn (design), camunda-process-mgmt
(deploy). Baseline arm drops every skill (``exclude="all"``) — the
v1 question is whether the suite as a whole earns its keep over the
model's training-time knowledge, not what any single skill adds in
isolation (that's a v2 ablation, once the suite-level signal is
positive).

Agent loop: ``react()`` with ``bash_session`` + ``text_editor`` +
``skill`` (all 13 skills discoverable). The INSTRUCTIONS block
carries only the Inspect-harness conventions (workspace persistence,
``submit()``) — every Camunda fact the agent needs is either in the
user prompt or discoverable via the skill tool. We deliberately
don't pre-load "a cluster is running" or "c8ctl is installed";
those are exactly the discoveries the skills are supposed to drive.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.agent import AgentPrompt, react
from inspect_ai.dataset import Sample
from inspect_ai.tool import bash_session, skill, text_editor

from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.cluster import process_deployed_on_cluster
from scorers.cpt import cpt_scorer
from scorers.lint import bpmn_lint_clean
from scorers.transcript import assert_tool_called
from solvers.boot_cluster import boot_cluster
from solvers.collect_artifacts import collect_artifacts

METADATA = ScenarioMetadata(
    skills=["camunda-bpmn", "camunda-process-mgmt"],
    tier="pr",
    baseline=BaselineConfig(mode="without-skill", exclude="all"),
)

INSTRUCTIONS = """\
Files you create only persist for review if they're under /workspace.
Anything you write to /tmp, the home directory, etc. is lost when the
session ends.

When you've completed the task, call submit() with a brief summary
of what you did.
"""


@task
def rocket_launch(arm: Arm = "with_skill") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.baseline.exclude)
    return Task(
        dataset=[
            Sample(
                id="happy",
                input=(
                    "Build me a tiny BPMN called RocketLaunch that "
                    "counts down 3, 2, 1 with a one-second pause "
                    "between each number, then lifts off, then ends. "
                    "Make it self-contained — no service tasks or "
                    "external workers. Deploy it to my local cluster "
                    "so I can watch it run."
                ),
            ),
            # edge-minimal sample is parked until happy path is reliably
            # green. Re-enable once scorers are stable end-to-end.
        ],
        solver=[
            boot_cluster(),
            react(
                prompt=AgentPrompt(instructions=INSTRUCTIONS),
                tools=[
                    bash_session(timeout=300),
                    text_editor(timeout=60),
                    *([skill(skill_dirs)] if skill_dirs else []),
                ],
            ),
            collect_artifacts(),
        ],
        scorer=[
            assert_tool_called("c8ctl", subcommand="deploy"),
            process_deployed_on_cluster("RocketLaunch"),
            bpmn_lint_clean(),
            cpt_scorer(project_dir="/scenarios/rocket-launch/cpt-verifier"),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-cpt-verifier.yaml")),
        metadata=METADATA.model_dump(),
    )
