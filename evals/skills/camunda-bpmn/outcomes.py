"""camunda-bpmn outcome eval: create a BPMN process that lints clean.

Failure mode: hand-written XML errors — missing DI blocks, bad coordinates,
fake-join gateways, and missing Zeebe extensions that cause ``c8ctl bpmn lint``
to report errors or warnings.

Each sample asks the agent to build a process and save it to
/workspace/process.bpmn. The ``bpmn_lint_clean`` scorer runs
``c8ctl bpmn lint`` on every *.bpmn under /workspace and scores 1.0
only when every file is clean. No live cluster needed — bpmn lint is a
static check, so the lighter advisory sandbox is sufficient.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.bpmn_lint import bpmn_lint_clean
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-bpmn"], max_sandboxes=2)

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
            "The process must contain, in order:\n"
            "1. A start event named 'Invoice received'\n"
            "2. A user task named 'Review invoice' "
            "(element id: ReviewInvoice, formId: review-invoice)\n"
            "3. A service task named 'Record decision' "
            "(element id: RecordDecision, type: record-decision)\n"
            "4. An end event named 'Done'\n"
            "All elements must be connected in sequence with sequence flows, "
            "and the process must include a BPMN DI diagram section." + SAVE
        ),
    ),
    Sample(
        id="exclusive-gateway-routing",
        input=(
            "Create a BPMN 2.0 process "
            "(process id: order-fulfillment, name: 'Order Fulfillment') that:\n"
            "1. Starts with an event named 'Order received'\n"
            "2. Has a service task 'Validate order' (type: validate-order)\n"
            "3. Routes via an exclusive (XOR) gateway named 'Amount exceeds limit?' — "
            "the condition branch for amount > 1000 leads to a service task "
            "'Approve manually' (type: manual-approval); the default branch leads to "
            "'Auto-approve' (type: auto-approval)\n"
            "4. Both branches merge at an exclusive (XOR) join gateway\n"
            "5. Continues to 'Send confirmation' (type: send-confirmation)\n"
            "6. Ends with an event named 'Done'\n"
            "Use a matching XOR join for the XOR fork. "
            "The process must include correct BPMN DI coordinates for all elements."
            + SAVE
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
            assert_skill_loaded("camunda-bpmn", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-advisory.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=300,
        token_limit=100_000,
        message_limit=50,
    )
