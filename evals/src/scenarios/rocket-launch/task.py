"""Rocket Launch BPMN deploy + run.

End-to-end: agent designs a small "rocket launch" BPMN and deploys it
to a running Camunda 8.9 cluster (provisioned by docker compose).
Three scorers compose to cover three failure modes at three costs:

1. Transcript — did the agent *attempt* ``c8ctl deploy`` at all?
2. Cluster — did the deploy actually land on the cluster?
3. CPT (Phase 2) — does the deployed BPMN behave correctly?

The CPT verifier brings up its own embedded Zeebe and does its own
deploy from the agent's BPMN file (mounted read-only); the cluster
scorer hits the Phase 1 cluster the agent worked against.

Load-bearing skills: camunda-bpmn (design), camunda-process-mgmt
(deploy). Baseline excludes camunda-bpmn (single load-bearing skill —
without-skill arm tests whether the model can produce a deployable
BPMN without the skill's element-template guidance).

Agent loop: ``react()`` with ``bash_session`` + ``text_editor`` +
``skill`` (all 13 skills discoverable). The system prompt only states
environment facts (cluster running, c8ctl on PATH) — it doesn't tell
the agent which skill to load or what order to do things in. Whether
the agent reaches for the skill tool is part of what the eval
measures.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.agent import AgentPrompt, react
from inspect_ai.dataset import Sample
from inspect_ai.tool import bash_session, skill, text_editor

from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR, all_skill_dirs
from scorers.cluster import process_deployed_on_cluster
from scorers.cpt import cpt_scorer
from scorers.transcript import assert_tool_called
from solvers.boot_cluster import boot_cluster

METADATA = ScenarioMetadata(
    skills=["camunda-bpmn", "camunda-process-mgmt"],
    tier="pr",
    verifier="composite",
    baseline=BaselineConfig(mode="without-skill", exclude=["camunda-bpmn"]),
)

INSTRUCTIONS = """\
You have access to a running Camunda 8.9 cluster on localhost:8080.
The c8ctl CLI is installed and on PATH.

When you've completed the task, call submit() with a brief summary
of what you did.
"""


@task
def rocket_launch() -> Task:
    return Task(
        dataset=[
            Sample(
                id="happy",
                input=(
                    "Build me a tiny BPMN called RocketLaunch — counts "
                    "down, then lifts off — and deploy it to my local "
                    "cluster so I can watch it run."
                ),
            ),
            Sample(
                id="edge-minimal",
                input=(
                    "Deploy the smallest possible BPMN you can to my "
                    "local Camunda cluster, name it RocketLaunch. I want "
                    "to confirm my setup actually works end-to-end."
                ),
            ),
        ],
        solver=[
            boot_cluster(),
            react(
                prompt=AgentPrompt(instructions=INSTRUCTIONS),
                tools=[
                    bash_session(timeout=300),
                    text_editor(timeout=60),
                    skill(all_skill_dirs()),
                ],
            ),
        ],
        scorer=[
            assert_tool_called("c8ctl", subcommand="deploy"),
            process_deployed_on_cluster("RocketLaunch"),
            cpt_scorer(project_dir="/scenarios/rocket-launch/cpt-verifier"),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-cpt-verifier.yaml")),
        metadata=METADATA.model_dump(),
    )
