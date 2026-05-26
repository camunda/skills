"""c8ctl bootstrap: install + connect to a running cluster.

Exercises the camunda-c8ctl skill's install + first-connection path
from the ``base`` image (no c8ctl pre-installed). The compose stack
brings up Camunda 8.9 orchestration before the agent runs, so the
cluster is healthy at task start — the scenario measures the
*agent's* install action, not the cluster boot.

Two scorers, two failure modes:

1. Transcript — did the agent reach for ``@camunda8/cli``? Catches
   the case where ``topology_reachable`` passes only because the
   image had c8ctl pre-baked (regression guard if the base image
   ever changes).
2. Cluster reachable — does ``c8ctl get topology --json`` return a
   valid topology with at least one broker? End-to-end proof the
   install worked, c8ctl is on PATH, and the default
   localhost:8080 fallback connects to the compose orchestration.

We don't use c8run as the runtime because it has no aarch64 build;
``camunda/camunda`` is multi-arch. The agent container shares
orchestration's network namespace, so c8ctl's default fallback
(localhost:8080) just works.

Agent loop: Inspect's ``react()`` driving ``bash_session`` (persistent
shell — npm install needs stable cwd/env), ``text_editor``
(Anthropic-native file ops, picked up by Claude models), and
``skill`` (all 13 skills discoverable, so trigger behavior falls out
of agent tool-choice rather than scenario config). INSTRUCTIONS
carries only Inspect-harness conventions (workspace persistence,
``submit()``); the cluster's existence and the install path are
*discoveries* the skill is supposed to drive, not pre-loads.
"""

from __future__ import annotations

import json

from inspect_ai import Task, task
from inspect_ai.agent import AgentPrompt, react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.tool import bash_session, grep, list_files, skill, text_editor
from inspect_ai.util import sandbox

from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.transcript import assert_tool_called

METADATA = ScenarioMetadata(
    skills=["camunda-c8ctl"],
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


@scorer(metrics=[])
def topology_reachable():
    """Score 1.0 when ``c8ctl get topology --json`` returns valid JSON
    with at least one broker; 0.0 otherwise.
    """

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        result = await sb.exec(["c8ctl", "get", "topology", "--json"], timeout=30)
        if result.returncode != 0:
            return Score(value=0.0, explanation=f"exit {result.returncode}: {result.stderr[-500:]}")
        try:
            topology = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return Score(value=0.0, explanation=f"non-JSON topology: {exc}")
        brokers = topology.get("brokers") or topology.get("Brokers") or []
        if not brokers:
            return Score(value=0.0, explanation=f"no brokers in topology: {topology}")
        return Score(
            value=1.0,
            explanation=f"{len(brokers)} broker(s) reachable",
            metadata={"topology": topology},
        )

    return score


@task
def c8ctl_bootstrap(arm: Arm = "with_skill") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.baseline.exclude)
    return Task(
        dataset=[
            Sample(
                id="happy",
                input=(
                    "There's a Camunda 8 cluster running somewhere on this "
                    "machine — can you set me up with a CLI so I can poke "
                    "at it?"
                ),
            ),
        ],
        solver=react(
            prompt=AgentPrompt(instructions=INSTRUCTIONS),
            tools=[
                bash_session(timeout=300),
                text_editor(timeout=60),
                grep(timeout=30),
                list_files(timeout=30),
                *([skill(skill_dirs)] if skill_dirs else []),
            ],
        ),
        scorer=[
            assert_tool_called("@camunda8/cli"),
            topology_reachable(),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-base.yaml")),
        metadata=METADATA.model_dump(),
        # Bounded so a flailing without-skill arm can't burn unbounded
        # quota. Simpler scenario than rocket-launch (no CPT, no BPMN
        # design) so caps sit lower.
        time_limit=240,
        token_limit=500_000,
        message_limit=60,
    )
