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
NS = {"bpmn": BPMN_NS}

# Maps each sample to the surefire test filter that exercises it.
# Surefire syntax: ClassName#methodName (selects all parameterized cases of that method).
SAMPLE_TESTS = {
    "linear-invoice-review": "CamundaBpmnIT#reviewInvoiceUserTaskIsReached",
    "exclusive-gateway-routing": "CamundaBpmnIT#xorGatewayRoutesCorrectly",
}

SAVE = "\n\nSave the finished process to /workspace/process.bpmn."


@scorer(metrics=[mean(), stderr()])
def xor_gateway_structure_valid(path: str = "/workspace/process.bpmn") -> Scorer:
    """Verify the XOR gateway's default flow is structural and conditionless."""

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

        gateway = next(
            (
                candidate
                for candidate in process.findall(".//bpmn:exclusiveGateway", NS)
                if candidate.get("default")
            ),
            None,
        )
        if gateway is None:
            return Score(
                value=0.0,
                explanation="order-fulfillment has no exclusive gateway with a default",
            )

        gateway_id = gateway.get("id")
        default_id = gateway.get("default")
        outgoing_flows = {
            flow.get("id"): flow
            for flow in process.findall("./bpmn:sequenceFlow", NS)
            if flow.get("sourceRef") == gateway_id and flow.get("id")
        }
        if default_id not in outgoing_flows:
            return Score(
                value=0.0,
                explanation=(
                    f"gateway default {default_id!r} is not an outgoing flow "
                    f"from gateway {gateway_id!r}"
                ),
            )

        default_flow = outgoing_flows[default_id]
        if default_flow.find("bpmn:conditionExpression", NS) is not None:
            return Score(
                value=0.0,
                explanation=f"default flow {default_id} must not have a condition",
            )

        if not any(
            flow.find("bpmn:conditionExpression", NS) is not None
            for flow in outgoing_flows.values()
            if flow.get("id") != default_id
        ):
            return Score(
                value=0.0,
                explanation="gateway needs a condition on a non-default outgoing flow",
            )

        return Score(
            value=1.0,
            explanation=(
                f"gateway {gateway_id} defaults to conditionless flow {default_id}"
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
            "(service task 'Auto-approve', type: auto-approval) via an explicit "
            "amount <= 1000 condition; manual approval must be the gateway's "
            "default fallback, with no condition on that default flow\n"
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
