"""camunda-c8ctl outcome eval: install c8ctl and use it against a live cluster.

Three samples, each with its own ``sandbox`` and ``setup``/``files``, showing
Inspect's per-sample sandbox configuration:

- ``install-cli``: base sandbox (no c8ctl pre-installed); agent installs and
  configures c8ctl. Scored by running ``c8ctl --version`` after the agent.
- ``get-topology``: with-c8ctl sandbox (pre-installed, live cluster); agent
  queries topology and saves JSON to ``/workspace/topology.json``. Scored by
  reading that file.
- ``deploy-process``: with-c8ctl sandbox; ``files`` seeds a minimal BPMN;
  agent deploys it. Scored via ``c8ctl list pd --json``.

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
from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.cluster import PROCESS_ID_KEYS
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = ScenarioMetadata(
    skills=["camunda-c8ctl"],
    baseline=BaselineConfig(exclude=["camunda-c8ctl"]),
)

# Wait for the Camunda REST API (port 8080) to be ready. The compose
# healthcheck covers port 9600 (actuator); there is a small gap before 8080
# accepts requests. Only needed on sandboxes with a live cluster.
WAIT_FOR_CLUSTER = (
    "timeout 60 bash -c "
    "'until c8ctl get topology --json >/dev/null 2>&1; do sleep 1; done'"
)

HELLO_BPMN = """\
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             xmlns:zeebe="http://camunda.org/schema/zeebe/1.0"
             targetNamespace="http://bpmn.io/schema/bpmn">
  <process id="HelloWorld" name="Hello World" isExecutable="true">
    <startEvent id="Start"/>
    <sequenceFlow id="Flow1" sourceRef="Start" targetRef="End"/>
    <endEvent id="End"/>
  </process>
</definitions>
"""

BASE_SANDBOX = ("docker", str(SANDBOXES_DIR / "compose-base.yaml"))
WITH_C8CTL_SANDBOX = ("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml"))


@scorer(metrics=[mean(), stderr()])
def c8ctl_outcome() -> Scorer:
    """Dispatch scorer keyed on ``state.metadata['check']``:

    - ``installed``: ``c8ctl --version`` exits 0.
    - ``topology``: ``/workspace/topology.json`` exists and is valid JSON.
    - ``deployed``: ``state.metadata['expected_process_id']`` found in
      ``c8ctl list pd --json``.
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

        if check == "topology":
            result = await sb.exec(["cat", "/workspace/topology.json"], timeout=10)
            if result.returncode != 0:
                return Score(
                    value=0.0, explanation="topology.json not created by agent"
                )
            try:
                json.loads(result.stdout)
                return Score(
                    value=1.0,
                    explanation=f"topology.json written ({len(result.stdout)} bytes)",
                )
            except json.JSONDecodeError:
                return Score(
                    value=0.0, explanation="topology.json contains invalid JSON"
                )

        if check == "deployed":
            expected_id = (state.metadata or {}).get("expected_process_id", "")
            result = await sb.exec(["c8ctl", "list", "pd", "--json"], timeout=60)
            if result.returncode != 0:
                return Score(
                    value=0.0,
                    explanation=f"c8ctl list pd exit {result.returncode}: {result.stderr[-300:]}",
                )
            if not result.stdout.strip():
                return Score(
                    value=0.0,
                    explanation=f"{expected_id}: cluster has no deployed processes",
                )
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                return Score(
                    value=0.0,
                    explanation=f"non-JSON response: {result.stdout[:200]}",
                )
            if isinstance(payload, list):
                definitions = payload
            elif isinstance(payload, dict):
                definitions = (
                    payload.get("items") or payload.get("processDefinitions") or []
                )
            else:
                definitions = []
            ids = [
                next((d.get(k) for k in PROCESS_ID_KEYS if d.get(k)), None)
                for d in definitions
                if isinstance(d, dict)
            ]
            ids = [i for i in ids if i]
            if expected_id in ids:
                return Score(
                    value=1.0,
                    explanation=f"{expected_id} deployed (found {len(ids)} definition(s))",
                    metadata={"deployed_ids": ids},
                )
            sample_keys = sorted(definitions[0].keys()) if definitions else []
            return Score(
                value=0.0,
                explanation=(
                    f"{expected_id} not deployed; found {ids} "
                    f"(first item keys: {sample_keys})"
                ),
                metadata={"deployed_ids": ids},
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
        setup=WAIT_FOR_CLUSTER,
        metadata={"check": "topology"},
    ),
    Sample(
        id="deploy-process",
        input="Deploy the BPMN process at /workspace/hello.bpmn to the cluster.",
        sandbox=WITH_C8CTL_SANDBOX,
        setup=WAIT_FOR_CLUSTER,
        files={"hello.bpmn": HELLO_BPMN},
        metadata={"check": "deployed", "expected_process_id": "HelloWorld"},
    ),
]


@task
def camunda_c8ctl(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.baseline.exclude)
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
