"""camunda-c8ctl outcome eval: use c8ctl against a live cluster.

Two samples, each with its own ``setup`` script and ``files`` pre-seeded into
the sandbox, demonstrating Inspect's per-sample sandbox setup API:

- ``get-topology``: ``setup`` waits for the REST API; agent is asked to query
  cluster topology and write the JSON to ``/workspace/topology.json``. Scored
  by verifying the file contains valid JSON.
- ``deploy-process``: ``setup`` waits for the REST API; ``files`` seeds a
  minimal BPMN into the workspace; agent deploys it. Scored by checking the
  cluster for the deployed process definition.

Both samples run in ``compose-with-c8ctl`` (c8ctl pre-installed, live cluster).
Skill-load is diagnostic; the without-skill arm drops camunda-c8ctl to measure
its value.

See ``scenarios/c8ctl-bootstrap/outcomes.py`` for the companion install-path
eval (base sandbox, no c8ctl pre-installed).
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

# Poll until the Camunda REST API is ready (port 9600 healthcheck passes before
# port 8080 is fully up; this closes the gap without boot_cluster() in the
# solver, which would require c8ctl to be available before the agent runs).
_WAIT_READY = (
    "timeout 60 bash -c "
    "'until c8ctl get topology --json >/dev/null 2>&1; do sleep 1; done'"
)

_HELLO_BPMN = """\
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


@scorer(metrics=[mean(), stderr()])
def c8ctl_usage_outcome() -> Scorer:
    """Dispatch scorer: reads ``state.metadata['check']`` to pick the oracle.

    - ``topology``: verify ``/workspace/topology.json`` was written and
      contains valid JSON.
    - ``deployed``: verify ``state.metadata['expected_process_id']`` appears
      in ``c8ctl list pd --json``.
    """

    async def score(state: TaskState, target: Target) -> Score:
        check = (state.metadata or {}).get("check")
        sb = sandbox()

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
        id="get-topology",
        input=(
            "Query the Camunda cluster topology using the available CLI tools "
            "and save the raw JSON output to /workspace/topology.json."
        ),
        setup=_WAIT_READY,
        metadata={"check": "topology"},
    ),
    Sample(
        id="deploy-process",
        input="Deploy the BPMN process at /workspace/hello.bpmn to the cluster.",
        setup=_WAIT_READY,
        files={"hello.bpmn": _HELLO_BPMN},
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
            c8ctl_usage_outcome(),
            assert_skill_loaded("camunda-c8ctl", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=300,
        token_limit=400_000,
        message_limit=50,
    )
