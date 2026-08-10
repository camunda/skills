"""camunda-job-workers — zero-dependency Node.js worker, end-to-end.

Unit under test: the ``references/worker-http-no-sdk.md`` sample — a worker
using only Node built-ins over the ``/v2/jobs/*`` REST API (no ``package.json``,
no ``node_modules``, no SDK). The agent writes the worker, deploys a fixed BPMN,
runs the worker against the live cluster, and starts an instance.

Three gating scorers:
  - worker_is_zero_dependency  — the worker really is built-ins-only (the capability)
  - process_deployed_on_cluster — the BPMN reached the cluster
  - cpt_scorer                  — the CPT verifier starts an instance of the same
      process and asserts it completes, which only the agent's real worker can do.

The BPMN is a fixed fixture (the prompt hands the agent the exact XML to save).
It is a test input, not the unit under test, so it is linted once at authoring.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.cluster import process_deployed_on_cluster
from scorers.cpt import cpt_scorer
from solvers.collect_artifacts import with_artifact_collection
from zero_dependency import worker_is_zero_dependency


METADATA = EvalMetadata(
    skills=["camunda-job-workers"],
)

# The exact BPMN the agent saves verbatim. Read from the CPT verifier's
# committed fixture rather than duplicated here, so the XML the prompt hands the
# agent and the XML the verifier deploys cannot drift apart. Fixed so the eval
# tests the worker, not BPMN authoring; `process-order` is the job type the
# worker must poll.
FIXTURE_BPMN = (
    Path(__file__).parent
    / "cpt-verifier"
    / "src"
    / "test"
    / "resources"
    / "NoSdkWorkerDemo.bpmn"
).read_text()

PROMPT = (
    "My Camunda 8 cluster is already running locally (don't start a new one). "
    "I need a job worker for it, but this environment has **no npm** — I can't "
    "install any packages. Write a worker in plain Node.js using only built-in "
    "modules (no `package.json`, no `node_modules`, no `@camunda8` SDK).\n\n"
    "Save this exact BPMN as `NoSdkWorkerDemo.bpmn` (process id `NoSdkWorkerDemo`, "
    "one service task with job type `process-order`):\n\n"
    "```xml\n" + FIXTURE_BPMN + "```\n\n"
    "Then:\n"
    "1. Write the zero-dependency worker that handles the `process-order` job type "
    "and completes each job.\n"
    "2. Deploy `NoSdkWorkerDemo.bpmn` to the running cluster.\n"
    "3. Start the worker in the background and leave it running — do not stop it.\n"
    "4. Start a process instance and confirm it runs to completion.\n"
)


@task
def camunda_job_workers(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=[
            Sample(id="no-sdk-worker-completes", input=PROMPT),
        ],
        solver=with_artifact_collection(build_agent(agent, skill_dirs)),
        scorer=[
            worker_is_zero_dependency(),
            process_deployed_on_cluster("NoSdkWorkerDemo"),
            cpt_scorer(project_dir="/skills/camunda-job-workers/cpt-verifier"),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-cpt-verifier.yaml")),
        metadata=METADATA.model_dump(),
        # time_limit covers the whole sample; Inspect reserves half for scoring,
        # so 720s leaves 360s for the CPT scorer's `mvn test`.
        time_limit=720,
        token_limit=700_000,
        message_limit=60,
    )
