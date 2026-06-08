"""camunda-bpmn outcome eval: author a BPMN process, lint-clean and behaviorally correct.

Two samples exercise the two canonical skill paths:

  linear-invoice-review     — user task + service task in sequence
  exclusive-gateway-routing — XOR gateway routing on a variable condition

Scorers:
  bpmn_lint_clean  — static: c8ctl bpmn lint reports zero errors/warnings
  cpt_scorer       — behavioral: CPT verifier deploys the BPMN and asserts
                     routing behavior (invoice-approval: reaches ReviewInvoice;
                     order-fulfillment: manual-approval for amount>1000,
                     auto-approval for amount<=1000)

  The CPT scorer selects the matching test method via surefire ``-Dtest=``
  rather than filtering inside the Java test, keeping the verifier plain JUnit.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.bpmn_lint import bpmn_lint_clean
from scorers.cpt import cpt_scorer
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-bpmn"], max_sandboxes=1)

# Maps each sample to the surefire test filter that exercises it.
# Surefire syntax: ClassName#methodName (selects all parameterized cases of that method).
SAMPLE_TESTS = {
    "linear-invoice-review": "CamundaBpmnIT#reviewInvoiceUserTaskIsReached",
    "exclusive-gateway-routing": "CamundaBpmnIT#xorGatewayRoutesCorrectly",
}

SAVE = (
    "\n\nSave the finished process to /workspace/process.bpmn. "
    "Run ``c8ctl bpmn lint /workspace/process.bpmn`` and fix every error "
    "and warning before finishing — the file must lint completely clean."
)

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
            "3. Route based on amount: orders over 1000 go to manual approval "
            "(service task 'Approve manually', type: manual-approval); "
            "smaller orders are auto-approved "
            "(service task 'Auto-approve', type: auto-approval)\n"
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
