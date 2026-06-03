"""camunda-c8ctl outcome eval: install c8ctl and use it against a live cluster.

Three samples, each with its own ``sandbox`` and ``setup``, showing Inspect's
per-sample sandbox configuration:

- ``install-cli``: base sandbox (no c8ctl pre-installed); agent installs and
  configures c8ctl. Scored by running ``c8ctl --version`` after the agent.
- ``get-topology``: with-c8ctl sandbox (pre-installed, live cluster); agent
  queries topology and saves JSON to ``/workspace/topology.json``. Scored by
  reading that file.
- ``list-users``: with-c8ctl sandbox; agent lists cluster users and saves JSON
  to ``/workspace/users.json``. Scored by reading that file.

A single ``c8ctl_outcome`` scorer dispatches on ``sample.metadata['check']``,
since Inspect scoring is task-level (no per-sample scorer field).

Skill-load is diagnostic; the without-skill arm drops camunda-c8ctl to measure
its value.
"""

from __future__ import annotations

import json

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-c8ctl"], max_sandboxes=3)

BASE_SANDBOX = ("docker", str(SANDBOXES_DIR / "compose-base.yaml"))
WITH_C8CTL_SANDBOX = ("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml"))


@scorer(metrics=[mean(), stderr()])
def c8ctl_outcome() -> Scorer:
    """Dispatch scorer keyed on ``state.metadata['check']``:

    - ``installed``: ``c8ctl --version`` exits 0.
    - ``topology``: ``/workspace/topology.json`` exists and is valid JSON.
    - ``users``: ``/workspace/users.json`` exists and is valid JSON.
    """

    async def score(state: TaskState, target: Target) -> Score:
        check = (state.metadata or {}).get("check")
        sb = sandbox()

        if check == "installed":
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

        if check in ("topology", "users"):
            output_file = f"/workspace/{check}.json"
            result = await sb.exec(["cat", output_file], timeout=10)
            if result.returncode != 0:
                return Score(
                    value=0.0,
                    explanation=f"{output_file} not created by agent",
                )
            try:
                json.loads(result.stdout)
                return Score(
                    value=1.0,
                    explanation=f"{output_file} written ({len(result.stdout)} bytes)",
                )
            except json.JSONDecodeError:
                return Score(
                    value=0.0,
                    explanation=f"{output_file} contains invalid JSON",
                )

        return Score(value=0.0, explanation=f"unknown check: {check!r}")

    return score


SAMPLES = [
    Sample(
        id="install-cli",
        input=(
            "There's a Camunda 8 cluster running at http://localhost:8080 — "
            "install the right command-line tool for it, configure it to "
            "connect to that address, and verify the connection using only "
            "the CLI you installed (no curl, no browser)."
        ),
        sandbox=BASE_SANDBOX,
        metadata={"check": "installed"},
    ),
    Sample(
        id="get-topology",
        input=(
            "Query the Camunda cluster topology using the available CLI tools "
            "and save the raw JSON output to /workspace/topology.json."
        ),
        sandbox=WITH_C8CTL_SANDBOX,
        metadata={"check": "topology"},
    ),
    Sample(
        id="list-users",
        input=(
            "List the users configured on the cluster using the available CLI "
            "tools and save the raw JSON output to /workspace/users.json."
        ),
        sandbox=WITH_C8CTL_SANDBOX,
        metadata={"check": "users"},
    ),
]


@task
def camunda_c8ctl(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        solver=with_artifact_collection(build_agent(agent, skill_dirs)),
        scorer=[
            c8ctl_outcome(),
            assert_skill_loaded("camunda-c8ctl", gating=False),
        ],
        metadata=METADATA.model_dump(),
        time_limit=300,
        token_limit=500_000,
        message_limit=60,
    )
