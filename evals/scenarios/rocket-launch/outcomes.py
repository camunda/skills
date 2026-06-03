"""Rocket Launch BPMN deploy + run.

Agent designs a small "rocket launch" BPMN and deploys it to a running
Camunda 8.9 cluster. Three outcome scorers: cluster (did the deploy
land?), lint (well-formed BPMN?), CPT (does it run to completion?).
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.cluster import process_deployed_on_cluster
from scorers.cpt import cpt_scorer
from scorers.lint import bpmn_lint_clean
from solvers.boot_cluster import boot_cluster
from solvers.collect_artifacts import with_artifact_collection


METADATA = EvalMetadata(
    skills=["camunda-bpmn", "camunda-process-mgmt"],
    without_skill_excludes="all",
)


@task
def rocket_launch(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=[
            Sample(
                id="timer-countdown",
                input=(
                    "I want a BPMN process with id `RocketLaunch` on "
                    "my local Camunda cluster (it's already running — "
                    "don't start a new one) — counts down 3, 2, 1 "
                    "with one-second pauses, then lifts off, then "
                    "ends. Just the BPMN file, please — self-contained, "
                    "no service tasks or workers, no Spring Boot or "
                    "Java glue. Deploy it and show me it running."
                ),
            ),
            # edge-minimal sample parked until timer-countdown is green.
        ],
        solver=[
            boot_cluster(),
            with_artifact_collection(build_agent(agent, skill_dirs)),
        ],
        scorer=[
            process_deployed_on_cluster("RocketLaunch"),
            bpmn_lint_clean(),
            cpt_scorer(project_dir="/scenarios/rocket-launch/cpt-verifier"),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-cpt-verifier.yaml")),
        metadata=METADATA.model_dump(),
        # time_limit covers the whole sample; Inspect gives scoring half
        # of it, so 720s leaves 360s for the CPT scorer's `mvn test`.
        time_limit=720,
        token_limit=800_000,
        message_limit=100,
    )
