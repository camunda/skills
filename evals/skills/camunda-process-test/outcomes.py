"""camunda-process-test outcome evals for specification and scenario authoring."""

from __future__ import annotations

import json
import re
from pathlib import Path

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
SPEC_PATH = "/workspace/TESTING.md"
SPEC_SAMPLE = "agentic-test-specification"
CONNECTOR_SPEC_SAMPLE = "connector-user-task-test-specification"
SIMPLE_SPEC_SAMPLE = "simple-user-task-test-specification"
SPEC_SAMPLES = {SPEC_SAMPLE, CONNECTOR_SPEC_SAMPLE, SIMPLE_SPEC_SAMPLE}
OPTIONAL_SPEC_FAILURE_PREFIXES = (
    "guarantees do not consistently",
    "guarantee rows are not concise",
    "test IDs and names must be unique",
    "integration plan lacks limitation",
    "agent plan does not reject incidental tool order",
    "agent guarantees lack negative tool isolation",
    "advanced assertions lack an explicit",
    "variable presence falsely claims",
    "manual checks lack a human or policy basis",
    "manual checks expose implementation identifiers",
    "plan is not concise",
)
OPTIONAL_SPEC_CRITERIA = len(OPTIONAL_SPEC_FAILURE_PREFIXES)

SAVE = "\n\nSave ONLY the scenario JSON to /workspace/invoice-approval.test.json."


def _spec_artifact(state: TaskState) -> str:
    artifacts = state.store.get("artifacts") or {}
    value = artifacts.get(SPEC_PATH, "")
    return value if isinstance(value, str) else ""


def _section(markdown: str, heading_pattern: str) -> str:
    lines = markdown.splitlines()
    matches: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading and re.fullmatch(heading_pattern, heading.group(2), re.IGNORECASE):
            matches.append((index, heading))
    if not matches:
        return ""
    index, heading = min(matches, key=lambda match: len(match[1].group(1)))
    level = len(heading.group(1))
    end = len(lines)
    for next_index in range(index + 1, len(lines)):
        next_heading = re.match(r"^(#{1,6})\s+", lines[next_index])
        if next_heading and len(next_heading.group(1)) <= level:
            end = next_index
            break
    return "\n".join(lines[index + 1 : end]).strip()


def _table_rows(section: str) -> list[str]:
    return [
        line
        for line in section.splitlines()
        if line.strip().startswith("|")
        and "---" not in line
        and not re.search(r"\|\s*(ID|Layer|#|Artifact)\s*\|", line, re.I)
    ]


@scorer(metrics=[mean(), stderr()])
def test_spec_complete() -> Scorer:
    """Score required, process-specific Markdown test-plan criteria."""

    async def score(state: TaskState, target: Target) -> Score:
        if state.sample_id not in SPEC_SAMPLES:
            return Score(
                value=1.0,
                explanation=f"not applicable to sample {state.sample_id}",
                metadata={"not_applicable": True},
            )
        markdown = _spec_artifact(state)
        if not markdown:
            return Score(value=0.0, explanation=f"missing {SPEC_PATH}")

        failures: list[str] = []
        suite_patterns = {
            "process": r"process tests?",
            "segment": r"(?:segment|point) integration tests?",
            "process integration": r"(?:process integration|e2e|end-to-end) tests?",
            "manual": r"manual tests?",
        }
        suites = {
            name: _section(markdown, pattern)
            for name, pattern in suite_patterns.items()
        }
        expected_suites = {
            SPEC_SAMPLE: {"process", "segment", "process integration", "manual"},
            CONNECTOR_SPEC_SAMPLE: {"process", "segment", "manual"},
            SIMPLE_SPEC_SAMPLE: {"process", "manual"},
        }[state.sample_id]
        unexpected_suites = {
            SPEC_SAMPLE: set(),
            CONNECTOR_SPEC_SAMPLE: {"process integration"},
            SIMPLE_SPEC_SAMPLE: {"segment", "process integration"},
        }[state.sample_id]

        for name in expected_suites:
            section = suites[name]
            if not section:
                failures.append(f"missing applicable {name} suite")
                continue
            for label in ("verifies", "required evidence", "mocks"):
                if not re.search(
                    rf"(?:\*\*\s*{label}\s*:\s*\*\*|^###\s+{label}\s*$)",
                    section,
                    re.I | re.M,
                ):
                    failures.append(f"{name} suite lacks {label}")
            rows = _table_rows(section)
            has_outcome_column = "guarantee" in section.lower() or (
                name == "manual" and "steps and pass condition" in section.lower()
            )
            if (
                not rows
                or not all(header in section.lower() for header in ("id", "test"))
                or not has_outcome_column
            ):
                failures.append(f"{name} suite lacks ID/Test/outcome rows")
            if not re.search(
                r"(?:\d+/\d+|\d{1,3}%\s+of\s+\w+|\b(?:all|every)\s+\w+)",
                section,
                re.I,
            ):
                failures.append(f"{name} suite lacks a measurable evidence gate")

        for name in unexpected_suites:
            if suites[name]:
                failures.append(f"irrelevant {name} suite included")

        guarantee_rows = [
            row for name in expected_suites for row in _table_rows(suites[name])
        ]
        derivable = re.compile(
            r"\b(?:activates?|cancels?|completes?|displays?|executes?|fires?|"
            r"appears?|handles?|includes?|processes?|provides?|reaches?|returns?|"
            r"routes?|selects?|shows?|triggers?|verif(?:y|ies)|visits?)\b",
            re.I,
        )
        if not guarantee_rows or any(
            not derivable.search(row) for row in guarantee_rows
        ):
            failures.append(
                "guarantees do not consistently imply observable assertions"
            )
        if any(len(row.split()) > 55 for row in guarantee_rows):
            failures.append("guarantee rows are not concise/direct")
        parsed_rows = [
            [cell.strip() for cell in row.strip().strip("|").split("|")]
            for row in guarantee_rows
        ]
        ids = [row[0] for row in parsed_rows if len(row) >= 3]
        tests = [row[1] for row in parsed_rows if len(row) >= 3]
        if len(ids) != len(set(ids)) or len(tests) != len(set(tests)):
            failures.append("test IDs and names must be unique")

        run = _section(markdown, r"(?:run and inspect|how to run|run instructions)")
        if not run:
            failures.append("missing run and inspect section")
        else:
            for term in ("prerequisite", "report"):
                if term not in run.lower():
                    failures.append(f"run section lacks {term}")
            if not re.search(
                r"(?:mvn(?:w)?(?:\s+-\S+)*\s+test|test studio)", run, re.I
            ):
                failures.append("run section lacks an executable automated workflow")
            if not re.search(r"(?:interactive|html)", run, re.I) or not re.search(
                r"(?:machine|json)", run, re.I
            ):
                failures.append("run section lacks interactive and machine reports")
            if not re.search(
                r"(?:handoff|provide|print|return|respond).{0,80}\breport\b|"
                r"\breport\b.{0,80}(?:handoff|provide|print|return|respond)",
                run,
                re.I,
            ):
                failures.append("run section lacks report handoff")
            if expected_suites & {"segment", "process integration"} and not re.search(
                r"(?:live|network|credential|public|model)", markdown, re.I
            ):
                failures.append("run section lacks live dependency boundary")

        artifacts = _section(markdown, r"artifacts?(?: and links| links)?")
        artifact_links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", artifacts)
        if len(artifact_links) < 3:
            failures.append("artifact section has fewer than 3 Markdown links")
        if any(target.strip() in {"", "#"} for target in artifact_links):
            failures.append("artifact section contains placeholder links")

        approval = _section(markdown, r"(?:approval|open questions.*approval)")
        if not re.search(r"\bstatus\s*:\s*(?:draft|approved)\b", markdown, re.I):
            failures.append("approval section lacks status")
        if not re.search(
            r"do not implement|before implementation|"
            r"implementation (?:will|may|can) proceed (?:only )?after .*approval",
            approval,
            re.I,
        ):
            failures.append("spec lacks an explicit approval gate")
        if re.search(r"approved for implementation", approval, re.I) and re.search(
            r"\bstatus\s*:\s*draft\b", markdown, re.I
        ):
            failures.append("approval state contradicts DRAFT status")

        if expected_suites & {"segment", "process integration"}:
            if not re.search(
                r"\b(?:limitation|boundary):|"
                r"\*\*mocks:\*\*.{0,120}\b(?:mock|local|replac)",
                markdown,
                re.I | re.S,
            ):
                failures.append("integration plan lacks limitation/boundary")
            if state.sample_id == SPEC_SAMPLE and not re.search(
                r"tool.{0,30}\bunordered\b|"
                r"(?:tool (?:invocation )?order|order).{0,30}not "
                r"(?:asserted|required|contractual)",
                markdown,
                re.I,
            ):
                failures.append("agent plan does not reject incidental tool order")
        if state.sample_id == SPEC_SAMPLE and not re.search(
            r"(?:only|exact(?:ly)?|exclud(?:e|es|ing)|"
            r"unrelated .{0,30}(?:inactive|not activated)|no (?:other )?tools?)",
            suites["segment"] + suites["process integration"],
            re.I,
        ):
            failures.append("agent guarantees lack negative tool isolation")
        if state.sample_id in {SPEC_SAMPLE, CONNECTOR_SPEC_SAMPLE}:
            tradeoff = re.search(
                r"test studio.{0,500}(?:native cpt|managed cpt|"
                r"assertion power|hybrid).{0,500}(?:guarantee|weaker|reduc|retain)",
                markdown,
                re.I | re.S,
            )
            if not tradeoff:
                failures.append(
                    "advanced assertions lack an explicit CPT/Test Studio "
                    "tradeoff and guarantee impact"
                )
            if re.search(
                r"(?:presence|existence) (?:alone )?"
                r"(?:proves?|guarantees?).{0,80}"
                r"(?:shape|non-empty|exclusive|semantic)",
                markdown,
                re.I,
            ):
                failures.append("variable presence falsely claims a stronger contract")
        if "manual" in expected_suites and not re.search(
            r"(?:policy|required|human|look and feel|observe)", suites["manual"], re.I
        ):
            failures.append("manual checks lack a human or policy basis")
        if re.search(
            r"\b(?:Activity|Event|Gateway|Task)_[A-Za-z0-9_]+\b|"
            r"\bjob type\b|\binternal variable\b",
            suites["manual"],
            re.I,
        ):
            failures.append("manual checks expose implementation identifiers")

        line_count = len(markdown.splitlines())
        if line_count > 220:
            failures.append("plan is not concise")
        optional_failures = [
            failure
            for failure in failures
            if failure.startswith(OPTIONAL_SPEC_FAILURE_PREFIXES)
        ]
        required_failures = [
            failure for failure in failures if failure not in optional_failures
        ]
        return Score(
            value=0.0 if required_failures else 1.0,
            explanation="; ".join(required_failures)
            or f"applicable suite plan with {len(guarantee_rows)} derivable guarantees",
            metadata={
                "expected_suites": sorted(expected_suites),
                "guarantees": len(guarantee_rows),
                "lines": line_count,
                "required_failures": required_failures,
                "optional_failures": optional_failures,
            },
        )

    return score


@scorer(metrics=[mean(), stderr()])
def test_spec_optional() -> Scorer:
    """Score non-gating planning-quality criteria."""

    async def score(state: TaskState, target: Target) -> Score:
        required = await test_spec_complete()(state, target)
        if required.metadata and required.metadata.get("not_applicable"):
            return required
        failures = (required.metadata or {}).get("optional_failures", [])
        return Score(
            value=max(0.0, 1.0 - len(failures) / OPTIONAL_SPEC_CRITERIA),
            explanation="; ".join(failures) or "all optional planning criteria pass",
            metadata={
                "optional_failures": failures,
                "optional_criteria": OPTIONAL_SPEC_CRITERIA,
            },
        )

    return score


@scorer(metrics=[mean(), stderr()])
def test_spec_overall() -> Scorer:
    """Combine the required gate and optional planning quality."""

    async def score(state: TaskState, target: Target) -> Score:
        required = await test_spec_complete()(state, target)
        if required.metadata and required.metadata.get("not_applicable"):
            return required
        optional = await test_spec_optional()(state, target)
        return Score(
            value=0.7 * float(required.value) + 0.3 * float(optional.value),
            explanation=(
                f"required={float(required.value):.2f}; "
                f"optional={float(optional.value):.2f}"
            ),
            metadata={
                "required": float(required.value),
                "optional": float(optional.value),
            },
        )

    return score


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


SPEC_PROMPT = """
Use the camunda-process-test skill to create the test specification for an
AI-agent process. For test-spec-first planning, write only `/workspace/TESTING.md`;
do not create test code, a Maven project, JSON scenarios, or reports.

The process has an AI Agent ad-hoc subprocess that can answer directly or call
four tools, then asks for user feedback. Rejected feedback loops through the
agent; accepted feedback completes the process. The realistic journey calls
two tools, receives rejected feedback, calls the other two tools, then receives
approval. Tool sets are unordered; generated wording is nondeterministic.
Mandatory CI must be deterministic and credential-free.

Include all applicable suites: `Process tests`, `Segment integration tests`,
`Process integration tests`, and `Manual tests`. In every suite include the
literal labels `Verifies`, `Required evidence`, and `Mocks`, plus an
`ID | Test | Guarantee` table. Evidence gates must be measurable and define
the counted population. Guarantees must imply concrete assertions, including
the exact expected tool set and inactive unrelated tools.

Add a limitation or boundary for live workers and external side effects. Add
`Run and inspect` with prerequisites, exact required automated and manual
workflows, `mvn test`, optional live execution, interactive HTML and machine
JSON report paths, and immediate report handoff. Add `Artifacts` with at least
three non-placeholder links. Finish with `Approval`, `Status: DRAFT`, open
decisions, and an explicit do-not-implement gate.

Record an unresolved choice between stronger native/managed CPT assertions,
weaker Test Studio-visible assertions, or a hybrid. State that variable
presence alone does not prove non-empty content, shape, or exclusivity, and
record how the choice retains or reduces each guarantee. Save only the polished
Markdown specification, then stop for human review.
"""

CONNECTOR_SPEC_PROMPT = """
Use the camunda-process-test skill to write only `/workspace/TESTING.md` for an
order-approval process with a start event, outbound payment connector, reviewer
user task and form, approved/rejected gateway, and two end events. The payment
contract is a status class and non-empty receipt identifier. There is no agent,
called process, or meaningful multi-component whole-process outcome.

Include only applicable suites: `Process tests`, `Segment integration tests`,
and `Manual tests`; do not add process-integration tests. Every suite needs
`Verifies`, measurable `Required evidence`, `Mocks`, and an
`ID | Test | Guarantee` table with positive and necessary negative assertions.
Manual tests use business language and an N/N policy-required gate.

Add the live/external boundary, prerequisites, `mvn test`, exact automated and
manual workflows, optional live execution, interactive HTML and machine JSON
reports, report handoff, and at least three non-placeholder artifact links.
Record an unresolved Test Studio versus stronger native/managed CPT choice for
receipt shape, including retained or reduced guarantees; variable presence
alone does not prove shape or non-empty content. Finish with `Approval`,
`Status: DRAFT`, open decisions, and an explicit do-not-implement gate.
"""

SIMPLE_SPEC_PROMPT = """
Use the camunda-process-test skill to write only `/workspace/TESTING.md` for a
simple expense-approval process with a start event, manager user task and form,
approved/rejected gateway, and two end events. It has no connectors, workers,
agents, called decisions, or external systems.

Include only `Process tests` and policy-required `Manual tests`; do not add
segment- or process-integration suites. Every suite needs `Verifies`,
measurable `Required evidence`, `Mocks`, and an `ID | Test | Guarantee` table.
Use an N/N gate for manual checks. Add prerequisites, `mvn test`, exact
automated and manual workflows, interactive HTML and machine JSON reports,
report handoff, and at least three non-placeholder artifact links. Finish with
`Approval`, `Status: DRAFT`, open decisions, and an explicit do-not-implement
gate. Keep the plan concise and save no other files.
"""

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
def camunda_process_test_spec(
    arm: Arm = "with_skill", agent: AgentKind = "react"
) -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=[
            Sample(id=SPEC_SAMPLE, input=SPEC_PROMPT),
            Sample(id=CONNECTOR_SPEC_SAMPLE, input=CONNECTOR_SPEC_PROMPT),
            Sample(id=SIMPLE_SPEC_SAMPLE, input=SIMPLE_SPEC_PROMPT),
        ],
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            test_spec_complete(),
            test_spec_optional(),
            test_spec_overall(),
            assert_skill_loaded("camunda-process-test", gating=False),
        ],
        sandbox=("docker", str(Path(__file__).with_name("compose-spec.yaml"))),
        metadata=METADATA.model_dump(),
        time_limit=900,
        token_limit=500_000,
        message_limit=50,
    )


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
