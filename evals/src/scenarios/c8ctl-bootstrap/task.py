"""c8ctl bootstrap: install + connect to a running cluster.

Exercises the camunda-c8ctl skill's install + first-connection path
from the ``base`` image (no c8ctl pre-installed). Success = the
agent installs c8ctl and confirms the cluster is healthy via
``c8ctl get topology --json``.

The Camunda 8.9 orchestration is brought up by docker compose (H2,
no external dependencies — see ``compose-base.yaml``). We don't use
c8run because it has no aarch64 build; the ``camunda/camunda`` image
is multi-arch. The agent container shares orchestration's network
namespace, so c8ctl's default fallback (localhost:8080) just works.

Verifier: exit-code + JSON-shape check on
``c8ctl get topology --json``. No CPT project needed — the artifact
the skill produces is a working CLI, not a process.

Agent loop: Inspect's ``react()`` driving ``bash_session`` (persistent
shell — npm install needs stable cwd/env), ``text_editor``
(Anthropic-native file ops, picked up by Claude models), and
``skill`` (all 13 skills discoverable, so trigger behavior falls out
of agent tool-choice rather than scenario config).
"""

from __future__ import annotations

import json

from inspect_ai import Task, task
from inspect_ai.agent import AgentPrompt, react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.tool import bash_session, skill, text_editor
from inspect_ai.util import sandbox

from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR, all_skill_dirs

METADATA = ScenarioMetadata(
    skills=["camunda-c8ctl"],
    tier="pr",
    verifier="exit-code",
    baseline=BaselineConfig(mode="without-skill", exclude=["camunda-c8ctl"]),
)

INSTRUCTIONS = """\
You're in a fresh Ubuntu container with a Camunda 8 cluster already
running on localhost:8080.

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
def c8ctl_bootstrap() -> Task:
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
            Sample(
                id="edge-health-check",
                input=(
                    "I think there's a Camunda cluster on localhost:8080 "
                    "but I'm not sure if it's actually healthy. Set me up "
                    "with the tooling to confirm."
                ),
            ),
        ],
        solver=react(
            prompt=AgentPrompt(instructions=INSTRUCTIONS),
            tools=[
                bash_session(timeout=300),
                text_editor(timeout=60),
                skill(all_skill_dirs()),
            ],
        ),
        scorer=topology_reachable(),
        sandbox=("docker", str(SANDBOXES_DIR / "compose-base.yaml")),
        metadata=METADATA.model_dump(),
    )
