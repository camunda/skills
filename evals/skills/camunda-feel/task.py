"""camunda-feel result eval: write a FEEL expression, evaluate it on the cluster.

Deterministic, no judge. Each sample asks for a single FEEL expression; the
agent saves it to /workspace/answer.feel; `feel_evaluates_to` runs it through
`c8ctl feel evaluate` (cluster engine) and checks the exact result.

Runs in a Docker sandbox with a live cluster (compose-with-c8ctl). Skill-load
is diagnostic; the without-skill arm drops camunda-feel to measure its value.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from core.agents import AgentKind, build_agent
from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.feel import feel_evaluates_to
from scorers.transcript import assert_skill_loaded
from solvers.boot_cluster import boot_cluster
from solvers.collect_artifacts import with_artifact_collection

METADATA = ScenarioMetadata(
    skills=["camunda-feel"],
    baseline=BaselineConfig(exclude=["camunda-feel"]),
)

_SAVE = (
    "\n\nWrite a single FEEL expression and save ONLY the expression to "
    "/workspace/answer.feel — one line, no `=` prefix, no surrounding quotes, "
    "no commentary."
)

_SAMPLES = [
    Sample(
        id="list-sum",
        input=(
            "Given a variable `items` that is a list where each entry has a "
            "numeric `price` field, compute the total price across all entries." + _SAVE
        ),
        metadata={
            "feel_vars": {"items": [{"price": 10}, {"price": 5}, {"price": 7}]},
            "feel_equals": 22,
        },
    ),
    Sample(
        id="bool-guard",
        input=(
            "Return true only when the variable `amount` is greater than 1000 "
            "and the variable `currency` equals \"EUR\"." + _SAVE
        ),
        metadata={
            "feel_vars": {"amount": 1500, "currency": "EUR"},
            "feel_equals": True,
        },
    ),
    Sample(
        id="string-greeting",
        input=(
            "Produce the string \"HELLO, \" followed by the variable `name` "
            "in upper case (e.g. name \"alice\" yields \"HELLO, ALICE\")." + _SAVE
        ),
        metadata={
            "feel_vars": {"name": "alice"},
            "feel_equals": "HELLO, ALICE",
        },
    ),
]


@task
def camunda_feel(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.baseline.exclude)
    return Task(
        dataset=_SAMPLES,
        solver=[
            boot_cluster(),
            with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        ],
        scorer=[
            feel_evaluates_to(),
            assert_skill_loaded("camunda-feel", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=300,
        token_limit=300_000,
        message_limit=40,
    )
