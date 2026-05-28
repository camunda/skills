"""c8ctl bootstrap: install c8ctl from a fresh container.

Exercises the camunda-c8ctl skill's install path from the ``base``
image (no c8ctl pre-installed). Outcome: ``c8ctl --version`` runs
cleanly in the sandbox after the agent finishes.

We previously scored on ``c8ctl get topology --json`` returning a
broker list, but that mixed two concerns: "agent installed c8ctl"
AND "the cluster is responsive." The agent only owns the first;
cluster responsiveness is a downstream concern owned by the compose
stack. A clean install with a cluster blip would have scored 0.0
under the old check, which is a false negative.

The compose stack still brings up Camunda 8.9 orchestration (other
scenarios use it, and the base image inherits the same compose
file), but this scenario's outcome no longer depends on cluster
state — only on whether c8ctl is on PATH and runs.

We don't use c8run as the runtime because it has no aarch64 build;
``camunda/camunda`` is multi-arch. The agent container shares
orchestration's network namespace, so c8ctl's default fallback
(localhost:8080) would just work if the agent did configure it —
but we don't require that here.

Agent loop is selectable via the ``agent`` task arg — see
``core.agents`` for the react/claude_code switch and the shared
INSTRUCTIONS conventions. The install path is a discovery the
skill is supposed to drive, not a pre-load.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from core.agents import AgentKind, build_agent
from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from solvers.collect_artifacts import with_artifact_collection

METADATA = ScenarioMetadata(
    skills=["camunda-c8ctl"],
    tier="pr",
    baseline=BaselineConfig(mode="without-skill", exclude="all"),
)


@scorer(metrics=[mean(), stderr()])
def c8ctl_installed():
    """Score 1.0 when ``c8ctl --version`` exits 0 in the sandbox.

    The base image ships without c8ctl, so a successful exit from
    ``c8ctl --version`` is direct proof the agent's install action
    landed. No cluster involvement; just "is the binary on PATH and
    does it run".
    """

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        result = await sb.exec(["c8ctl", "--version"], timeout=10)
        if result.returncode == 0:
            return Score(
                value=1.0,
                explanation=f"c8ctl --version → {result.stdout.strip()}",
                metadata={"version_output": result.stdout},
            )
        return Score(
            value=0.0,
            explanation=(
                f"c8ctl --version exit {result.returncode}: "
                f"{(result.stderr or result.stdout)[-300:]}"
            ),
        )

    return score


@task
def c8ctl_bootstrap(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.baseline.exclude)
    return Task(
        dataset=[
            Sample(
                id="happy",
                input=(
                    "There's a Camunda 8 cluster already running somewhere "
                    "on this machine (don't start a new one) — can you set "
                    "me up with a CLI so I can poke at it?"
                ),
            ),
        ],
        solver=with_artifact_collection(build_agent(agent, skill_dirs)),
        scorer=c8ctl_installed(),
        sandbox=("docker", str(SANDBOXES_DIR / "compose-base.yaml")),
        metadata=METADATA.model_dump(),
        # Bounded so a flailing without-skill arm can't burn unbounded
        # quota. Simpler scenario than rocket-launch (no CPT, no BPMN
        # design) so caps sit lower.
        time_limit=240,
        token_limit=500_000,
        message_limit=60,
    )
