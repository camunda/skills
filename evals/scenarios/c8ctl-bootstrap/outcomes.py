"""c8ctl bootstrap: install c8ctl from a fresh container.

Exercises the camunda-c8ctl skill's install path from the ``base``
image (no c8ctl pre-installed); scored on whether ``c8ctl --version``
runs cleanly afterward. The compose stack uses ``camunda/camunda``
(multi-arch) rather than c8run (no aarch64 build), but this scenario's
outcome doesn't depend on cluster state.
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
    baseline=BaselineConfig(exclude="all"),
)


@scorer(metrics=[mean(), stderr()])
def c8ctl_installed():
    """Score 1.0 when ``c8ctl --version`` exits 0 in the sandbox."""

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
        # Lower caps than rocket-launch: no CPT, no BPMN design.
        time_limit=240,
        token_limit=500_000,
        message_limit=60,
    )
