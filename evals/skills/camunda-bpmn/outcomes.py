"""camunda-bpmn outcome eval: author a BPMN process, lint-clean and behaviorally correct.

Two samples exercise the two canonical skill paths:

  linear-invoice-review     — user task + service task in sequence
  exclusive-gateway-routing — XOR gateway routing on a variable condition

Scorers:
  bpmn_lint_clean  — static: c8ctl bpmn lint reports zero errors/warnings
  cpt_scorer       — behavioral: CPT verifier deploys the BPMN and asserts
                     routing behavior (invoice-approval: reaches ReviewInvoice;
                     order-fulfillment: manual-approval for amount>1000,
                     auto-approval for amount<=1000, and manual-approval as the
                     safe default for a missing amount)

  The CPT scorer selects the matching test method via surefire ``-Dtest=``
  rather than filtering inside the Java test, keeping the verifier plain JUnit.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.bpmn_lint import bpmn_lint_clean
from scorers.cpt import cpt_scorer
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-bpmn"], max_sandboxes=1)

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
ZEEBE_NS = "http://camunda.org/schema/zeebe/1.0"
NS = {"bpmn": BPMN_NS, "zeebe": ZEEBE_NS}

# Maps each sample to the surefire test filter that exercises it.
# Surefire syntax: ClassName#methodName (selects all parameterized cases of that method).
SAMPLE_TESTS = {
    "linear-invoice-review": "CamundaBpmnIT#reviewInvoiceUserTaskIsReached",
    "exclusive-gateway-routing": "CamundaBpmnIT#xorGatewayRoutesCorrectly",
}

SAVE = "\n\nSave the finished process to /workspace/process.bpmn."


def _task_type(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    task_definition = element.find(
        "./bpmn:extensionElements/zeebe:taskDefinition",
        NS,
    )
    return task_definition.get("type") if task_definition is not None else None


@scorer(metrics=[mean(), stderr()])
def xor_gateway_structure_valid(path: str = "/workspace/process.bpmn") -> Scorer:
    """Verify the amount-routing XOR gateway's safe default structure."""

    async def score(state: TaskState, target: Target) -> Score:
        if state.sample_id != "exclusive-gateway-routing":
            return Score(
                value=1.0,
                explanation="XOR gateway structure check not applicable to this sample",
            )

        result = await sandbox().exec(["cat", path], timeout=10)
        if result.returncode != 0:
            return Score(value=0.0, explanation=f"missing BPMN artifact at {path}")

        try:
            root = ET.fromstring(result.stdout)
        except ET.ParseError as exc:
            return Score(value=0.0, explanation=f"invalid BPMN XML: {exc}")

        process = root.find(".//bpmn:process[@id='order-fulfillment']", NS)
        if process is None:
            return Score(
                value=0.0,
                explanation="process id order-fulfillment not found",
            )

        elements = {
            element.get("id"): element
            for element in process.iter()
            if element.get("id")
        }
        sequence_flows = list(process.iter(f"{{{BPMN_NS}}}sequenceFlow"))
        routing_gateways = []
        for candidate in process.iter(f"{{{BPMN_NS}}}exclusiveGateway"):
            gateway_id = candidate.get("id")
            outgoing_flows = [
                flow
                for flow in sequence_flows
                if flow.get("sourceRef") == gateway_id
            ]
            target_types = {
                _task_type(elements.get(flow.get("targetRef")))
                for flow in outgoing_flows
            }
            if {"manual-approval", "auto-approval"}.issubset(target_types):
                routing_gateways.append((candidate, outgoing_flows))

        if not routing_gateways:
            return Score(
                value=0.0,
                explanation=(
                    "order-fulfillment has no exclusive gateway whose outgoing "
                    "flows target manual-approval and auto-approval"
                ),
            )

        for gateway, outgoing_flows in routing_gateways:
            gateway_id = gateway.get("id")
            default_id = gateway.get("default")
            outgoing_by_id = {
                flow.get("id"): flow
                for flow in outgoing_flows
                if flow.get("id")
            }
            if default_id not in outgoing_by_id:
                return Score(
                    value=0.0,
                    explanation=(
                        f"gateway {gateway_id!r} default {default_id!r} is not "
                        "one of its outgoing flows"
                    ),
                )

            default_flow = outgoing_by_id[default_id]
            if default_flow.find("bpmn:conditionExpression", NS) is not None:
                return Score(
                    value=0.0,
                    explanation=f"default flow {default_id} must not have a condition",
                )

            if _task_type(elements.get(default_flow.get("targetRef"))) != "manual-approval":
                return Score(
                    value=0.0,
                    explanation=(
                        f"gateway {gateway_id} default flow {default_id} must "
                        "target manual-approval"
                    ),
                )

            if not any(
                _task_type(elements.get(flow.get("targetRef"))) == "auto-approval"
                and flow.find("bpmn:conditionExpression", NS) is not None
                for flow in outgoing_flows
                if flow.get("id") != default_id
            ):
                return Score(
                    value=0.0,
                    explanation=(
                        f"gateway {gateway_id} needs a condition on the "
                        "non-default auto-approval flow"
                    ),
                )

        return Score(
            value=1.0,
            explanation=(
                "amount-routing gateway(s) default to conditionless "
                "manual-approval flow(s)"
            ),
        )

    return score


SAMPLES = [
    Sample(
        id="linear-invoice-review",
        input=(
            "Create a BPMN 2.0 process for invoice approval "
            "(process id: invoice-approval, name: 'Invoice Approval'). "
            "The process must contain:\n"
            "1. A start event named 'Invoice received'\n"
            "2. A user task named 'Review invoice' "
            "(element id: ReviewInvoice, formId: review-invoice)\n"
            "3. A service task named 'Record decision' "
            "(element id: RecordDecision, type: record-decision)\n"
            "4. An end event named 'Done'" + SAVE
        ),
    ),
    Sample(
        id="exclusive-gateway-routing",
        input=(
            "Model an order fulfillment process "
            "(process id: order-fulfillment, name: 'Order Fulfillment'):\n"
            "1. Start when an order arrives ('Order received')\n"
            "2. Validate the order (service task 'Validate order', type: validate-order)\n"
            "3. Route based on amount with an exclusive gateway: orders over 1000 "
            "go to manual approval (service task 'Approve manually', "
            "type: manual-approval); orders at or below 1000 go to auto-approval "
            "(service task 'Auto-approve', type: auto-approval) using this "
            "type-safe condition: "
            "`=if number(string(amount)) != null then "
            "number(string(amount)) <= 1000 else false`; the condition must "
            "return false, not raise an evaluation error, when amount is missing "
            "or non-numeric; manual approval must be the gateway's default "
            "fallback, with no condition on that default flow\n"
            "4. After either path, send a confirmation "
            "(service task 'Send confirmation', type: send-confirmation)\n"
            "5. End the process ('Done')" + SAVE
        ),
    ),
]


@task
def camunda_bpmn(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        # submit=False: .bpmn file is the deliverable; halt once it's lint-clean.
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            bpmn_lint_clean(),
            xor_gateway_structure_valid(),
            cpt_scorer(
                project_dir="/skills/camunda-bpmn/cpt-verifier",
                mvn_extra=lambda sid: (
                    [f"-Dtest={SAMPLE_TESTS[sid]}"] if sid in SAMPLE_TESTS else []
                ),
            ),
            assert_skill_loaded("camunda-bpmn", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-cpt-verifier.yaml")),
        metadata=METADATA.model_dump(),
        # time_limit covers agent run + CPT scoring; 720s leaves ~360s for mvn test.
        time_limit=720,
        token_limit=100_000,
        message_limit=50,
    )
