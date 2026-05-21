"""c8ctl bootstrap from a clean container.

Exercises the camunda-c8ctl skill's install + first-cluster path
from the ``base`` image (no c8ctl pre-installed). Success = the
agent installs c8ctl, starts a local cluster, and confirms topology.

Verifier: exit-code + JSON-shape check on
``c8ctl get topology --json``. No CPT project needed — the artifact
the skill produces is a working CLI, not a process.

Agent loop: Inspect's ``react()`` driving ``bash_session`` (persistent
shell — npm install + cluster start need stable cwd/env),
``text_editor`` (Anthropic-native file ops, picked up by Claude
models), and ``skill`` (all 13 skills discoverable, so trigger
behavior falls out of agent tool-choice rather than scenario config).
"""

from __future__ import annotations

import json

from inspect_ai import Task, task
from inspect_ai.agent import react
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
                    "I want to play with a local Camunda 8 cluster on my "
                    "laptop — can you help me get set up?"
                ),
            ),
            Sample(
                id="edge-already-running",
                input=(
                    "I think I've already got a Camunda cluster running "
                    "locally from yesterday but I'm not sure if it's "
                    "healthy — can you check?"
                ),
            ),
        ],
        solver=react(
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
