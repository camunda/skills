"""camunda-process-test outcome eval: author a deterministic CPT scenario file."""

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

METADATA = EvalMetadata(skills=["camunda-process-test"], max_sandboxes=1)

SCENARIO_PATH = "/workspace/invoice-approval.test.json"

SAVE = "\n\nSave ONLY the scenario JSON to /workspace/invoice-approval.test.json."


@scorer(metrics=[mean(), stderr()])
def cpt_scenario_shape() -> Scorer:
    """Check that the authored `.test.json` covers both gateway outcomes."""

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        read = await sb.exec(["cat", SCENARIO_PATH], timeout=10)
        if read.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"missing scenario file at {SCENARIO_PATH}",
            )

        try:
            payload = json.loads(read.stdout)
        except json.JSONDecodeError as exc:
            return Score(value=0.0, explanation=f"invalid JSON: {exc}")

        test_cases = payload.get("testCases")
        if not isinstance(test_cases, list) or len(test_cases) != 2:
            return Score(
                value=0.0,
                explanation="testCases must contain exactly 2 branch scenarios",
            )

        required = [
            ("approved-branch", True, "NotifyApproved", "ApprovedEnd"),
            ("rejected-branch", False, "NotifyRejected", "RejectedEnd"),
        ]

        def _elements(instruction: dict) -> set[str]:
            selectors = instruction.get("elementSelectors")
            if not isinstance(selectors, list):
                return set()
            return {
                e.get("elementId")
                for e in selectors
                if isinstance(e, dict) and isinstance(e.get("elementId"), str)
            }

        for label, approved_value, job_element, end_event in required:
            matching_case = None
            for case in test_cases:
                if not isinstance(case, dict):
                    continue
                instructions = case.get("instructions")
                if not isinstance(instructions, list):
                    continue
                for inst in instructions:
                    variables = (
                        inst.get("variables") if isinstance(inst, dict) else None
                    )
                    approved = (
                        variables.get("approved")
                        if isinstance(variables, dict)
                        else None
                    )
                    if (
                        isinstance(inst, dict)
                        and inst.get("type") == "CREATE_PROCESS_INSTANCE"
                        and approved == approved_value
                    ):
                        matching_case = case
                        break
                if matching_case:
                    break

            if matching_case is None:
                return Score(
                    value=0.0,
                    explanation=(
                        f"{label}: missing CREATE_PROCESS_INSTANCE with "
                        f"approved={approved_value}"
                    ),
                )

            instructions = matching_case.get("instructions") or []
            active_asserts = [
                inst
                for inst in instructions
                if isinstance(inst, dict)
                and inst.get("type") == "ASSERT_ELEMENT_INSTANCES"
                and inst.get("state") == "IS_ACTIVE"
            ]
            completed_asserts = [
                inst
                for inst in instructions
                if isinstance(inst, dict)
                and inst.get("type") == "ASSERT_ELEMENT_INSTANCES"
                and inst.get("state") == "IS_COMPLETED"
            ]
            process_done = any(
                isinstance(inst, dict)
                and inst.get("type") == "ASSERT_PROCESS_INSTANCE"
                and inst.get("state") == "IS_COMPLETED"
                for inst in instructions
            )

            if not any(job_element in _elements(inst) for inst in active_asserts):
                return Score(
                    value=0.0,
                    explanation=f"{label}: missing IS_ACTIVE assertion for {job_element}",
                )
            if not any(end_event in _elements(inst) for inst in completed_asserts):
                return Score(
                    value=0.0,
                    explanation=f"{label}: missing IS_COMPLETED assertion for {end_event}",
                )
            if not process_done:
                return Score(
                    value=0.0,
                    explanation=f"{label}: missing ASSERT_PROCESS_INSTANCE IS_COMPLETED",
                )

        return Score(
            value=1.0,
            explanation="scenario JSON covers both gateway outcomes deterministically",
        )

    return score


SAMPLES = [
    Sample(
        id="invoice-approval-two-outcomes",
        input=(
            "Author one Camunda Process Test instruction file for processDefinitionId "
            "`invoice-approval` with exactly two test cases, one per XOR outcome.\n"
            "Process shape:\n"
            "- StartEvent_InvoiceReceived -> ReviewInvoice (user task)\n"
            "- Gateway_Approved?\n"
            "- approved=true path -> NotifyApproved (service task) -> ApprovedEnd\n"
            "- approved=false path -> NotifyRejected (service task) -> RejectedEnd\n\n"
            "Requirements:\n"
            "1) Use CPT `.test.json` instruction format.\n"
            "2) In each test case: CREATE_PROCESS_INSTANCE sets `approved` to route "
            "the intended branch.\n"
            "3) Assert the branch service task is active (ASSERT_ELEMENT_INSTANCES "
            "state IS_ACTIVE).\n"
            "4) Assert the matching end event completed (ASSERT_ELEMENT_INSTANCES "
            "state IS_COMPLETED).\n"
            "5) Assert process completion (ASSERT_PROCESS_INSTANCE state "
            "IS_COMPLETED)." + SAVE
        ),
    )
]


@task
def camunda_process_test(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            cpt_scenario_shape(),
            assert_skill_loaded("camunda-process-test", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-advisory.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=300,
        token_limit=120_000,
        message_limit=40,
    )
