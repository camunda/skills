"""camunda-connectors-development outcome eval: author a JSON-only connector template.

Deterministic, machine-checkable eval. The agent must write a specialized
outbound element template JSON file and satisfy exact structural constraints
(top-level metadata, hidden infrastructure properties, bindings, and property
ordering for FEEL references).
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

METADATA = EvalMetadata(skills=["camunda-connectors-development"], max_sandboxes=10)


@scorer(metrics=[mean(), stderr()])
def connector_template_valid() -> Scorer:
    """Validate the generated connector template JSON artifact."""

    async def score(state: TaskState, target: Target) -> Score:
        output_file = (state.metadata or {}).get(
            "output_file", "/workspace/element-template.json"
        )

        result = await sandbox().exec(["cat", output_file], timeout=10)
        if result.returncode != 0:
            return Score(value=0.0, explanation=f"{output_file} not created")

        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return Score(value=0.0, explanation=f"invalid JSON: {exc}")

        template = parsed[0] if isinstance(parsed, list) and parsed else parsed
        if not isinstance(template, dict):
            return Score(value=0.0, explanation="template must be a JSON object")

        failures: list[str] = []

        if template.get("id") != "io.camunda.acme.customer.lookup.v1":
            failures.append("id mismatch")
        if template.get("name") != "Customer lookup":
            failures.append("name mismatch")
        if template.get("version") != 1:
            failures.append("version must be 1")

        applies_to = template.get("appliesTo") or []
        if "bpmn:ServiceTask" not in applies_to:
            failures.append("appliesTo must include bpmn:ServiceTask")

        element_type = template.get("elementType") or {}
        if element_type.get("value") != "bpmn:ServiceTask":
            failures.append("elementType.value must be bpmn:ServiceTask")

        properties = template.get("properties")
        if not isinstance(properties, list):
            failures.append("properties must be an array")
            properties = []

        by_id = {
            p.get("id"): p
            for p in properties
            if isinstance(p, dict) and isinstance(p.get("id"), str)
        }

        required_ids = ["customerId", "endpointPath", "method", "baseUrl"]
        missing = [pid for pid in required_ids if pid not in by_id]
        if missing:
            failures.append(f"missing properties: {', '.join(missing)}")

        if "customerId" in by_id:
            binding = by_id["customerId"].get("binding") or {}
            if (
                binding.get("type") != "zeebe:input"
                or binding.get("name") != "customerId"
            ):
                failures.append("customerId binding must be zeebe:input/customerId")

        if "endpointPath" in by_id:
            endpoint = by_id["endpointPath"]
            if endpoint.get("type") != "Hidden":
                failures.append("endpointPath must be Hidden")
            value = str(endpoint.get("value", ""))
            if "customerId" not in value:
                failures.append("endpointPath value must reference customerId")

        if "method" in by_id:
            method = by_id["method"]
            if method.get("type") != "Hidden" or method.get("value") != "GET":
                failures.append("method must be Hidden with value GET")

        if "baseUrl" in by_id:
            base_url = by_id["baseUrl"]
            if (
                base_url.get("type") != "Hidden"
                or base_url.get("value") != "https://customer-api.internal"
            ):
                failures.append(
                    "baseUrl must be Hidden with value https://customer-api.internal"
                )

        ids_in_order = [p.get("id") for p in properties if isinstance(p, dict)]
        if "customerId" in ids_in_order and "endpointPath" in ids_in_order:
            if ids_in_order.index("customerId") > ids_in_order.index("endpointPath"):
                failures.append("customerId must appear before endpointPath")

        if failures:
            return Score(value=0.0, explanation="; ".join(failures))

        return Score(value=1.0, explanation="template satisfies all structural checks")

    return score


SAMPLES = [
    Sample(
        id="path-a-template-specialization",
        input=(
            "Create a Camunda element template JSON file for a reusable internal "
            "customer lookup connector and save it to /workspace/element-template.json. "
            "It must be JSON (object or single-item array) and satisfy ALL constraints:\n"
            "- id: io.camunda.acme.customer.lookup.v1\n"
            "- name: Customer lookup\n"
            "- version: 1\n"
            "- appliesTo includes bpmn:ServiceTask\n"
            "- elementType.value: bpmn:ServiceTask\n"
            "- properties include exactly these IDs at minimum: customerId, endpointPath, method, baseUrl\n"
            "- customerId uses binding type zeebe:input with binding name customerId\n"
            "- endpointPath is Hidden and its value references customerId\n"
            "- method is Hidden with value GET\n"
            "- baseUrl is Hidden with value https://customer-api.internal\n"
            "- customerId appears before endpointPath in the properties array.\n"
            "Return a brief confirmation after writing the file."
        ),
        metadata={"output_file": "/workspace/element-template.json"},
    )
]


@task
def camunda_connectors_development(
    arm: Arm = "with_skill", agent: AgentKind = "react"
) -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        # submit=False: /workspace/element-template.json is the deliverable.
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            connector_template_valid(),
            assert_skill_loaded("camunda-connectors-development", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-advisory.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=240,
        token_limit=100_000,
        message_limit=40,
    )
