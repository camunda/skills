"""camunda-process-mgmt outcome eval: deploy and operate a live process on-cluster.

Deterministic, machine-checkable scoring:
- process_deployed_on_cluster: confirms the BPMN process ID is deployed.
- process_instance_completed: validates the created instance reaches COMPLETED.

The sample focuses on runtime operations (deploy/start/complete user task)
rather than BPMN design, while still being fully self-contained in sandbox.
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
from scorers.cluster import process_deployed_on_cluster
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-process-mgmt"])

PROCESS_ID = "ProcessMgmtOutcome"
RESULT_PATH = "/workspace/process_mgmt_result.json"


@scorer(metrics=[mean(), stderr()])
def process_instance_completed() -> Scorer:
    """Score 1.0 when the agent records an instance key that is COMPLETED."""

    async def score(state: TaskState, target: Target) -> Score:
        path = (state.metadata or {}).get("result_path", RESULT_PATH)
        sb = sandbox()

        result_file = await sb.exec(["cat", path], timeout=10)
        if result_file.returncode != 0 or not (result_file.stdout or "").strip():
            return Score(value=0.0, explanation=f"missing result file at {path}")

        try:
            payload = json.loads(result_file.stdout)
        except json.JSONDecodeError as exc:
            return Score(
                value=0.0,
                explanation=f"result file is not valid JSON: {exc}",
                metadata={"raw": (result_file.stdout or "")[:500]},
            )

        instance_key = str(payload.get("instanceKey") or "").strip()
        task_key = str(payload.get("completedUserTaskKey") or "").strip()
        if not instance_key:
            return Score(value=0.0, explanation="result JSON missing instanceKey")
        if not task_key:
            return Score(
                value=0.0,
                explanation="result JSON missing completedUserTaskKey",
                metadata={"instanceKey": instance_key},
            )

        pi = await sb.exec(
            ["c8ctl", "get", "pi", instance_key, "--json", "--fields=key,state,bpmnProcessId"],
            timeout=60,
        )
        if pi.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"c8ctl get pi {instance_key} exit {pi.returncode}: {(pi.stderr or '')[-300:]}",
                metadata={"instanceKey": instance_key},
            )

        try:
            pi_payload = json.loads(pi.stdout)
        except json.JSONDecodeError as exc:
            return Score(
                value=0.0,
                explanation=f"get pi returned non-JSON: {exc}",
                metadata={
                    "instanceKey": instance_key,
                    "raw_stdout": (pi.stdout or "")[:500],
                },
            )

        # Resolve the data dict: c8ctl may return a flat dict or wrap it in an
        # "item" key; with --fields we prefer the flat shape when present.
        data: dict = {}
        if isinstance(pi_payload, dict):
            if "state" in pi_payload or "bpmnProcessId" in pi_payload:
                data = pi_payload
            elif isinstance(pi_payload.get("item"), dict):
                data = pi_payload["item"]
            else:
                data = pi_payload

        # Validate the instance belongs to the expected process to avoid false
        # positives from unrelated processes that happen to reach COMPLETED.
        bpmn_id = data.get("bpmnProcessId")
        if bpmn_id and bpmn_id != PROCESS_ID:
            return Score(
                value=0.0,
                explanation=(
                    f"instance {instance_key} belongs to '{bpmn_id}', "
                    f"not expected '{PROCESS_ID}'"
                ),
                metadata={"instanceKey": instance_key, "bpmnProcessId": bpmn_id},
            )

        state_value = (
            data.get("state")
            or data.get("State")
            or data.get("processInstanceState")
        )

        normalized = str(state_value or "").upper()
        completed = normalized == "COMPLETED"
        return Score(
            value=1.0 if completed else 0.0,
            explanation=(
                f"instance {instance_key} state {normalized or '<missing>'}; "
                f"completed user task {task_key}"
            ),
            metadata={
                "instanceKey": instance_key,
                "completedUserTaskKey": task_key,
                "state": state_value,
                "bpmnProcessId": bpmn_id,
            },
        )

    return score


SAMPLES = [
    Sample(
        id="deploy-start-complete",
        input=(
            "Use c8ctl to run a full process-management flow on the local cluster.\n"
            "Create /workspace/process.bpmn with process id ProcessMgmtOutcome and this behavior: "
            "start event -> user task 'Review request' (id ReviewRequest) -> end event.\n"
            "Then do all of the following:\n"
            "1) Deploy /workspace/process.bpmn\n"
            "2) Start one instance of ProcessMgmtOutcome and capture its instance key\n"
            "3) Find the user task for that instance and complete it\n"
            "4) Verify the instance reaches COMPLETED\n"
            "5) Save /workspace/process_mgmt_result.json with exactly: "
            "{\"instanceKey\": \"<key>\", \"completedUserTaskKey\": \"<taskKey>\"}\n"
            "Use --profile=local on mutating c8ctl commands."
        ),
        metadata={"result_path": RESULT_PATH},
    )
]


@task
def camunda_process_mgmt(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        solver=with_artifact_collection(build_agent(agent, skill_dirs)),
        scorer=[
            process_deployed_on_cluster(PROCESS_ID),
            process_instance_completed(),
            assert_skill_loaded("camunda-process-mgmt", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=420,
        token_limit=150_000,
        message_limit=60,
    )
