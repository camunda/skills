"""Rocket Launch BPMN deploy + run.

End-to-end: agent designs a small "rocket launch" BPMN and deploys it
to a running Camunda 8.9 cluster (provisioned by docker compose).
Three independent scorers — each its own column on the Inspect
dashboard — cover three outcome failure modes:

1. Cluster — did the deploy actually land on the cluster?
2. Lint — is the deployed BPMN well-formed (`c8ctl bpmn lint`)?
3. CPT — does the deployed process actually run to completion?

No transcript / tool-call scorer: how the agent gets the BPMN onto
the cluster (``c8ctl deploy``, ``c8 deploy`` via the npm alias,
direct Zeebe REST POST, etc.) is implementation detail. The outcome
scorers carry the signal. See feedback memory
``feedback_skill_loaded_is_trigger_scorer`` for the broader
trigger-vs-outcome framing.

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

Agent loop is selectable via the ``agent`` task arg — see
``core.agents`` for the react/claude_code switch and the shared
workspace conventions. Environmental facts the agent can't discover
(e.g. "the cluster is already running") live in the user prompt;
implementation hints (port numbers, c8ctl install path, tool names)
stay out so the skills get tested as the discovery surface.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from core.agents import AgentKind, build_agent
from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.cluster import process_deployed_on_cluster
from scorers.cpt import cpt_scorer
from scorers.lint import bpmn_lint_clean
from solvers.boot_cluster import boot_cluster
from solvers.collect_artifacts import with_artifact_collection


METADATA = ScenarioMetadata(
    skills=["camunda-bpmn", "camunda-process-mgmt"],
    tier="pr",
    baseline=BaselineConfig(mode="without-skill", exclude="all"),
)


@task
def rocket_launch(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.baseline.exclude)
    return Task(
        dataset=[
            Sample(
                id="happy",
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
            # edge-minimal sample is parked until happy path is reliably
            # green. Re-enable once scorers are stable end-to-end.
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
        # Bounded so a flailing without-skill arm can't burn unbounded
        # quota. With-skill arm landed at ~3 min / 330k tokens; caps
        # are tight enough to terminate a no-progress loop quickly.
        # time_limit covers the whole sample (solver + scoring), and
        # Inspect allots scoring half of it (`time_limit / 2`). The
        # CPT scorer runs `mvn test` (~30-90s on a working BPMN, +30s
        # ConditionTimeout on a broken one), so we set 720s → scoring
        # gets 360s, comfortably above mvn worst-case.
        time_limit=720,
        token_limit=800_000,
        message_limit=100,
    )
