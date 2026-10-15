"""camunda-process-test outcome evals for specification and scenario authoring."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import Arm, skill_dirs_for_arm
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-process-test"], max_sandboxes=1)

SPEC_PATH = "/workspace/TESTING.md"
PROCESS_ID = "ai-agent-chat-with-tools"
TOOLS = {"ListUsers", "Search_Recipe", "Jokes_API", "Activity_0x3prgn"}
FEEDBACK = "User_Feedback"
SPEC_SAMPLE = "agentic-test-specification"
CONNECTOR_SPEC_SAMPLE = "connector-user-task-test-specification"
SIMPLE_SPEC_SAMPLE = "simple-user-task-test-specification"
SPEC_SAMPLES = {SPEC_SAMPLE, CONNECTOR_SPEC_SAMPLE, SIMPLE_SPEC_SAMPLE}
IMPLEMENTATION_SAMPLE = "agentic-three-layer-suite"
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


def _not_applicable(state: TaskState, sample_id: str) -> Score | None:
    if state.sample_id == sample_id:
        return None
    return Score(
        value=1.0,
        explanation=f"not applicable to sample {state.sample_id}",
        metadata={"not_applicable": True},
    )


def _artifacts(state: TaskState) -> dict[str, str]:
    return {
        path: content
        for path, content in (state.store.get("artifacts") or {}).items()
        if isinstance(path, str) and isinstance(content, str)
    }


def _artifact(state: TaskState) -> str:
    artifacts = _artifacts(state)
    value = artifacts.get(SPEC_PATH, "")
    return value if isinstance(value, str) else ""


def _json_documents(state: TaskState) -> list[tuple[str, dict[str, Any]]]:
    documents = []
    for path, content in _artifacts(state).items():
        if not path.endswith(".json"):
            continue
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            documents.append((path, value))
    return documents


def _test_cases(state: TaskState) -> list[tuple[str, dict[str, Any]]]:
    cases = []
    for path, document in _json_documents(state):
        if document.get("processId") != PROCESS_ID:
            continue
        for case in document.get("testCases", []):
            if isinstance(case, dict):
                cases.append((path, case))
    return cases


def _instructions(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        instruction
        for instruction in case.get("instructions", [])
        if isinstance(instruction, dict)
    ]


def _mentioned_elements(case: dict[str, Any]) -> set[str]:
    return {
        value
        for instruction in _instructions(case)
        for value in re.findall(r'"elementId"\s*:\s*"([^"]+)"', json.dumps(instruction))
    }


def _summary(state: TaskState) -> tuple[str, dict[str, Any]] | None:
    required = {
        "processCoverage",
        "integrationCoverage",
        "e2eOutcomes",
        "suites",
        "redundancy",
    }
    for path, document in _json_documents(state):
        if required.issubset(document):
            return path, document
    return None


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
def artifact_scorer() -> Scorer:
    """Require the approved spec and runnable, separated test-layer artifacts."""

    async def score(state: TaskState, target: Target) -> Score:
        if skipped := _not_applicable(state, IMPLEMENTATION_SAMPLE):
            return skipped
        files = _artifacts(state)
        cases = _test_cases(state)
        failures = []
        if not _artifact(state) or not re.search(
            r"\bAPPROVED\b", _artifact(state), re.IGNORECASE
        ):
            failures.append("missing approved TESTING.md")
        if not any(path.endswith("pom.xml") for path in files):
            failures.append("missing Maven harness")
        poms = [path for path in files if path.endswith("pom.xml")]
        if sorted(poms) != ["/workspace/test/pom.xml"]:
            failures.append(
                "expected exactly the approved Maven harness at /workspace/test/pom.xml"
            )
        if not any(
            path.endswith(".bpmn") and PROCESS_ID in text
            for path, text in files.items()
        ):
            failures.append("missing canonical BPMN")
        if not cases:
            failures.append("missing importable CPT JSON with top-level processId")
        if any(
            "placeholder" in text.lower()
            for path, text in files.items()
            if path.endswith((".java", ".kt"))
        ):
            failures.append("placeholder test source is not executable evidence")
        generated_test_sources = sorted(
            path
            for path in files
            if path.startswith("/workspace/test/src/test/java/")
            and Path(path).name not in {"ProcessTest.java", "TestApplication.java"}
        )
        if generated_test_sources:
            failures.append(
                f"unexpected generated test sources: {generated_test_sources}"
            )
        names = [case.get("name") for _, case in cases]
        if any(not isinstance(name, str) or " — " not in name for name in names):
            failures.append("scenario names must use '<who/what> — <outcome>'")
        corpus = "\n".join(f"{path}\n{text}" for path, text in files.items()).lower()
        for layer, pattern in {
            "deterministic": r"\bdeterministic\b",
            "point integration": r"\bpoint[- ]integration\b",
            "E2E": r"\be2e\b|end[- ]to[- ]end",
        }.items():
            if not re.search(pattern, corpus):
                failures.append(f"missing separated {layer} artifact")
        if "live-dev" not in corpus and "live dev" not in corpus:
            failures.append("missing optional live-dev documentation")
        return Score(
            value=0.0 if failures else 1.0,
            explanation="; ".join(failures)
            or f"approved runnable three-layer harness with {len(cases)} JSON scenarios",
        )

    return score


@scorer(metrics=[mean(), stderr()])
def build_scorer() -> Scorer:
    """Compile and execute the generated default suite in the offline verifier."""

    async def score(state: TaskState, target: Target) -> Score:
        if skipped := _not_applicable(state, IMPLEMENTATION_SAMPLE):
            return skipped
        verifier = sandbox("verifier")
        prep = await verifier.exec(
            [
                "sh",
                "-c",
                "cp -R /agent-workspace/. /verifier-workspace/ "
                "&& mkdir -p "
                "/verifier-workspace/test/src/test/java/io/camunda/tests "
                "/verifier-workspace/test/src/test/resources/processes "
                "/verifier-workspace/test/src/test/resources/forms "
                "&& cp /fixture/TESTING.md /verifier-workspace/TESTING.md "
                "&& cp /fixture/pom.xml /verifier-workspace/test/pom.xml "
                "&& cp /fixture/ProcessTest.java "
                "/verifier-workspace/test/src/test/java/io/camunda/tests/ "
                "&& cp /fixture/TestApplication.java "
                "/verifier-workspace/test/src/test/java/io/camunda/tests/ "
                "&& cp /fixture/ai-agent-chat-with-tools.bpmn "
                "/verifier-workspace/test/src/test/resources/processes/ "
                "&& cp /fixture/ai-agent-chat-initial-request.form "
                "/fixture/ai-agent-chat-user-feedback.form "
                "/verifier-workspace/test/src/test/resources/forms/ "
                "&& find /verifier-workspace -name pom.xml "
                "-not -path '*/target/*' -print -quit",
            ],
            timeout=30,
        )
        pom = "/verifier-workspace/test/pom.xml"
        if prep.returncode != 0 or not pom:
            return Score(value=0.0, explanation="generated Maven pom.xml not found")
        pom_probe = await verifier.exec(["test", "-f", pom], timeout=10)
        if pom_probe.returncode != 0:
            return Score(value=0.0, explanation=f"generated Maven pom missing: {pom}")
        await verifier.exec(["rm", "-rf", str(Path(pom).parent / "target")], timeout=30)
        run = await verifier.exec(["mvn", "-B", "-o", "-f", pom, "test"], timeout=900)
        output = "\n".join(filter(None, [run.stdout, run.stderr]))
        evidence = [
            line
            for line in output.splitlines()
            if "Tests run:" in line or "BUILD " in line or "[ERROR]" in line
        ]
        tests = [int(match) for match in re.findall(r"Tests run:\s*(\d+)", output)]
        passed = run.returncode == 0 and bool(tests) and sum(tests) > 0
        return Score(
            value=1.0 if passed else 0.0,
            explanation="\n".join(evidence[-30:])
            or f"offline Maven exited {run.returncode}; tests={sum(tests)}",
            metadata={
                "mvn_returncode": run.returncode,
                "tests_run": sum(tests),
                "raw_tail": output[-2000:],
            },
        )

    return score


@scorer(metrics=[mean(), stderr()])
def process_coverage_scorer() -> Scorer:
    """Require machine evidence for complete reachable BPMN and flow coverage."""

    async def score(state: TaskState, target: Target) -> Score:
        if skipped := _not_applicable(state, IMPLEMENTATION_SAMPLE):
            return skipped
        found = _summary(state)
        if not found:
            return Score(
                value=0.0,
                explanation="missing combined machine-readable coverage summary",
            )
        path, data = found
        coverage = data["processCoverage"]
        keys = (
            "reachableElements",
            "coveredElements",
            "reachableSequenceFlows",
            "coveredSequenceFlows",
        )
        complete = isinstance(coverage, dict) and all(
            isinstance(coverage.get(key), int) for key in keys
        )
        if complete:
            complete = (
                coverage["reachableElements"] > 0
                and coverage["reachableElements"] == coverage["coveredElements"]
                and coverage["reachableSequenceFlows"] > 0
                and coverage["reachableSequenceFlows"]
                == coverage["coveredSequenceFlows"]
            )
        if isinstance(coverage, dict) and coverage.get("unreachableElements"):
            complete = complete and coverage.get("bpmnDefectsReported") is True
        return Score(value=1.0 if complete else 0.0, explanation=f"{path}: {coverage}")

    return score


@scorer(metrics=[mean(), stderr()])
def integration_path_scorer() -> Scorer:
    """Require an isolated point-integration JSON scenario for every tool."""

    async def score(state: TaskState, target: Target) -> Score:
        if skipped := _not_applicable(state, IMPLEMENTATION_SAMPLE):
            return skipped
        covered = set()
        invalid = []
        for _, case in _test_cases(state):
            instructions = _instructions(case)
            activated_ids = {
                activation.get("elementId")
                for instruction in instructions
                if instruction.get("type") == "COMPLETE_JOB_AD_HOC_SUB_PROCESS"
                and instruction.get("completionConditionFulfilled") is False
                for activation in instruction.get("activateElements", [])
                if isinstance(activation, dict)
            }
            intended = activated_ids & TOOLS
            if len(intended) != 1:
                continue
            tool = next(iter(intended))
            completed = any(
                instruction.get("state") == "IS_COMPLETED"
                and tool in _mentioned_elements({"instructions": [instruction]})
                for instruction in instructions
            )
            job_completed = any(
                instruction.get("type") == "COMPLETE_JOB"
                and instruction.get("jobSelector", {}).get("elementId") == tool
                for instruction in instructions
            )
            not_activated = {
                selector.get("elementId")
                for instruction in instructions
                if instruction.get("state") == "IS_NOT_ACTIVATED"
                for selector in instruction.get("elementSelectors", [])
                if isinstance(selector, dict) and selector.get("elementId")
            }
            if (
                completed
                and job_completed
                and ((TOOLS - {tool}) | {FEEDBACK}).issubset(not_activated)
            ):
                covered.add(tool)
            else:
                invalid.append(tool)
        missing = sorted(TOOLS - covered)
        return Score(
            value=0.0 if missing or invalid else 1.0,
            explanation=f"covered={sorted(covered)} missing={missing} invalid={sorted(invalid)}",
        )

    return score


@scorer(metrics=[mean(), stderr()])
def e2e_scorer() -> Scorer:
    """Require a named feedback/retry outcome that reaches every expected tool."""

    async def score(state: TaskState, target: Target) -> Score:
        if skipped := _not_applicable(state, IMPLEMENTATION_SAMPLE):
            return skipped
        matches = []
        for _, case in _test_cases(state):
            instructions = _instructions(case)
            feedback_values = [
                instruction.get("variables", {}).get("userSatisfied")
                for instruction in instructions
                if instruction.get("type") == "COMPLETE_USER_TASK"
                and isinstance(instruction.get("variables"), dict)
            ]
            process_done = any(
                instruction.get("type") == "ASSERT_PROCESS_INSTANCE"
                and instruction.get("state") == "IS_COMPLETED"
                for instruction in instructions
            )
            ahsp_true = sum(
                instruction.get("type") == "COMPLETE_JOB_AD_HOC_SUB_PROCESS"
                and instruction.get("completionConditionFulfilled") is True
                for instruction in instructions
            )
            ahsp_false = sum(
                instruction.get("type") == "COMPLETE_JOB_AD_HOC_SUB_PROCESS"
                and instruction.get("completionConditionFulfilled") is False
                for instruction in instructions
            )
            completed_jobs = {
                instruction.get("jobSelector", {}).get("elementId")
                for instruction in instructions
                if instruction.get("type") == "COMPLETE_JOB"
            }
            if (
                False in feedback_values
                and True in feedback_values
                and TOOLS.issubset(_mentioned_elements(case))
                and ahsp_true >= 2
                and ahsp_false >= 2
                and TOOLS.issubset(completed_jobs)
                and process_done
                and " — " in str(case.get("name", ""))
            ):
                matches.append(case.get("name"))
        return Score(
            value=1.0 if matches else 0.0,
            explanation=f"named feedback/retry E2E outcomes: {matches}",
        )

    return score


@scorer(metrics=[mean(), stderr()])
def isolation_scorer() -> Scorer:
    """Reject mandatory tests that call public services, models, or credentials."""

    async def score(state: TaskState, target: Target) -> Score:
        if skipped := _not_applicable(state, IMPLEMENTATION_SAMPLE):
            return skipped
        suspicious = []
        for path, text in _artifacts(state).items():
            lower_path = path.lower()
            if (
                lower_path.endswith((".bpmn", ".md"))
                or "live" in lower_path
                or not lower_path.endswith(
                    (".java", ".kt", ".yml", ".yaml", ".properties", ".xml")
                )
            ):
                continue
            for marker in (
                "api.openai.com",
                "api.anthropic.com",
                "system.getenv(",
                'WebClient.create("http',
                'new URL("http',
            ):
                if marker.lower() in text.lower():
                    suspicious.append(f"{path}: {marker}")
        return Score(
            value=0.0 if suspicious else 1.0,
            explanation="; ".join(suspicious)
            or "mandatory suite contains no public/model client or credential access",
        )

    return score


@scorer(metrics=[mean(), stderr()])
def redundancy_scorer() -> Scorer:
    """Require per-layer leave-one-out evidence and overlap justification."""

    async def score(state: TaskState, target: Target) -> Score:
        if skipped := _not_applicable(state, IMPLEMENTATION_SAMPLE):
            return skipped
        found = _summary(state)
        redundancy = found[1]["redundancy"] if found else {}
        layers = redundancy.get("layers", {}) if isinstance(redundancy, dict) else {}
        valid = all(
            isinstance(layers.get(layer), dict)
            and layers[layer].get("leaveOneOutApplied") is True
            and layers[layer].get("redundantScenarios") == []
            for layer in ("deterministic", "pointIntegration", "e2e")
        )
        valid = valid and bool(redundancy.get("crossLayerOverlapExplanation"))
        return Score(
            value=1.0 if valid else 0.0, explanation=f"redundancy={redundancy}"
        )

    return score


@scorer(metrics=[mean(), stderr()])
def report_scorer() -> Scorer:
    """Require machine and HTML suite/run-level coverage evidence."""

    async def score(state: TaskState, target: Target) -> Score:
        if skipped := _not_applicable(state, IMPLEMENTATION_SAMPLE):
            return skipped
        files = _artifacts(state)
        found = _summary(state)
        html = [
            path
            for path, text in files.items()
            if path.endswith(".html")
            and ("COVERAGE_DATA" in text or "completedElements" in text)
        ]
        data = found[1] if found else {}
        suites = data.get("suites", [])
        integration = data.get("integrationCoverage", {})
        covered_tools = set(integration.get("coveredTools", []))
        integration_complete = covered_tools == TOOLS and integration.get(
            "totalPaths"
        ) == len(TOOLS)
        outcomes = data.get("e2eOutcomes", [])
        valid_suites = (
            isinstance(suites, list)
            and len(suites) >= 3
            and all(
                isinstance(suite, dict)
                and isinstance(suite.get("runs"), list)
                and suite["runs"]
                for suite in suites
            )
        )
        valid_outcomes = isinstance(outcomes, list) and bool(outcomes)
        return Score(
            value=1.0
            if found
            and html
            and valid_suites
            and integration_complete
            and valid_outcomes
            else 0.0,
            explanation=(
                f"machine={found[0] if found else None} html={html} "
                f"suites={len(suites) if isinstance(suites, list) else 0} "
                f"integration={sorted(covered_tools)} "
                f"e2e={len(outcomes) if isinstance(outcomes, list) else 0}"
            ),
        )

    return score


@scorer(metrics=[mean(), stderr()])
def report_handoff_scorer() -> Scorer:
    """Require opening or immediately surfacing the absolute HTML report path."""

    async def score(state: TaskState, target: Target) -> Score:
        if skipped := _not_applicable(state, IMPLEMENTATION_SAMPLE):
            return skipped
        transcript = "\n".join(
            str(getattr(message, "content", ""))
            for message in state.messages
            if getattr(message, "role", None) == "assistant"
        )
        for message in state.messages:
            if getattr(message, "role", None) != "assistant":
                continue
            for call in getattr(message, "tool_calls", None) or []:
                transcript += "\n" + json.dumps(call.arguments or {})
        path = re.search(r"/workspace/[^\s\"']*report[^\s\"']*\.html", transcript)
        valid_path = path is not None and "..." not in path.group(0)
        opened = bool(re.search(r"\b(open|xdg-open|start)\b[^\n]*\.html", transcript))
        return Score(
            value=1.0 if valid_path or opened else 0.0,
            explanation=(
                f"report handoff path={path.group(0) if valid_path else None}, "
                f"opened={opened}"
            ),
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

IMPLEMENTATION_PROMPT = f"""
Your first action must load the `camunda-process-test` skill. The user has
approved `/fixture/TESTING.md`. Use that skill
to implement that specification against
`/fixture/ai-agent-chat-with-tools.bpmn`. Build the generated test artifacts
under `/workspace/test`.

The approved `TESTING.md`, pinned `pom.xml`, canonical BPMN, JUnit runner,
Spring application, `generate-report-summary.py`, and `validate-output.py` are
already installed read-only
at their final `/workspace` paths. Do not copy, rewrite, summarize, edit, or
replace them. Generate only scenario JSON, the machine summary, optional
live-dev documentation, and the HTML report.

`/fixture/canonical-scenarios.test.json` is the upstream passing CPT reference
for this exact process. Read and reuse its valid agent state, job selector,
tool activation, feedback-loop, and assertion shapes instead of inventing CPT
instructions. Reorganize those outcomes into the three required layer files
and add isolated point-integration cases; the scorers execute the result and
judge behavior rather than byte equality.

Completion has four non-negotiable gates: exactly three scenario JSON files,
a passing offline Maven run, `/workspace/report-summary.json` plus the CPT HTML
report, and a passing no-argument `validate-output.py` run. The first Maven
success is only the midpoint; never respond with a summary before all four
gates pass. Do not add Java/Kotlin test classes or modify the approved runner.

Do not `cat`, open, or read the full BPMN: it contains large embedded base64
icons that will exhaust context. Use the supplied process topology and exact
element IDs in this prompt. Copy the BPMN without inspecting it. If a specific
XML fact is indispensable, use a narrow `grep` that excludes
`modelerTemplateIcon` lines.

The read-only POM's Spring Boot 4.0.0 and `camunda-process-test-spring` 8.9.5
dependencies are present in the verifier's offline Maven cache. The local
Camunda runtime is available at `localhost:8080`; there is no Docker socket and
no external network.

Implement all three separately identifiable layers from the approved spec:
Keep the implementation economical: create exactly three scenario files named
`deterministic.test.json`, `point-integration.test.json`, and `e2e.test.json`.
The point-integration file contains its four tool cases. Do not create one file
per requirement or extra speculative scenarios.

Process topology: `StartEvent_1` routes through `Gateway_0z6ctwk` into the
`AI_Agent` ad-hoc subprocess. Its tools are `ListUsers`, `Search_Recipe`,
`Jokes_API`, and `Activity_0x3prgn`. `User_Feedback` routes through
`Gateway_1dcg4ha`: false loops back to `Gateway_0z6ctwk`; true reaches
`Event_0i39jej`.

1. Deterministic process tests use importable CPT JSON with top-level
   `processId` `{PROCESS_ID}` wherever the instruction format is sufficient,
   plus Java only for orchestration JSON cannot express. They cover 100% of
   reachable elements and sequence flows, both feedback outcomes, the retry
   loop, the no-tool path, and all four tools.
2. Point integration has one isolated JSON scenario per tool. Each starts the
   process normally, activates exactly that tool through the AI Agent ad-hoc
   subprocess, asserts it completed, and asserts the other tools and
   `{FEEDBACK}` were not activated.
3. Mocked/local E2E contains a named full-process outcome that reaches
   {", ".join(sorted(TOOLS))}, rejects the first response with follow-up input,
   then approves and completes. Assert the tool set, not tool order or prose.

Every `testCases[].name` uses the Unicode em dash exactly as
`<who/what> — <outcome>`; ASCII hyphens fail the gate. Required tests are offline,
credential-free, and run under default `mvn test`; document optional live-dev
execution separately. Apply leave-one-out analysis within each layer and
explain valid cross-layer overlap.

Every `.test.json` file must be one JSON object, never a top-level array:

```json
{{
  "processId": "{PROCESS_ID}",
  "testCases": [
    {{
      "name": "Who or what — named outcome",
      "instructions": []
    }}
  ]
}}
```

For each point-integration case, use these exact instruction shapes:

```json
[
  {{
    "type": "CREATE_PROCESS_INSTANCE",
    "processDefinitionSelector": {{
      "processDefinitionId": "{PROCESS_ID}"
    }}
  }},
  {{
    "type": "COMPLETE_JOB_AD_HOC_SUB_PROCESS",
    "jobSelector": {{
      "jobType": "io.camunda.agenticai:aiagent:subprocess:2"
    }},
    "completionConditionFulfilled": false,
    "activateElements": [{{"elementId": "TOOL_ID"}}]
  }},
  {{
    "type": "COMPLETE_JOB",
    "jobSelector": {{"elementId": "TOOL_ID"}},
    "variables": {{"toolCallResult": {{}}}}
  }},
  {{
    "type": "ASSERT_ELEMENT_INSTANCE",
    "processInstanceSelector": {{
      "processDefinitionId": "{PROCESS_ID}"
    }},
    "elementSelector": {{"elementId": "TOOL_ID"}},
    "state": "IS_COMPLETED"
  }},
  {{
    "type": "ASSERT_ELEMENT_INSTANCES",
    "processInstanceSelector": {{
      "processDefinitionId": "{PROCESS_ID}"
    }},
    "elementSelectors": [
      {{"elementId": "OTHER_TOOL_ID"}},
      {{"elementId": "{FEEDBACK}"}}
    ],
    "state": "IS_NOT_ACTIVATED"
  }}
]
```

Every `ASSERT_ELEMENT_INSTANCE`, `ASSERT_ELEMENT_INSTANCES`, and
`ASSERT_PROCESS_INSTANCE` instruction must include
`processInstanceSelector.processDefinitionId: "{PROCESS_ID}"`; omitting it
makes the entire JSON file unreadable by CPT.

For full-process and point-integration cases, omit `startInstructions`
entirely. A start instruction targeting `StartEvent_1` is invalid because
start events are not supported instruction targets.

Use this exact feedback instruction shape; `jobSelector` is invalid here:

```json
{{
  "type": "COMPLETE_USER_TASK",
  "userTaskSelector": {{"elementId": "{FEEDBACK}"}},
  "variables": {{"userSatisfied": true}}
}}
```

The E2E case must include element assertions for all four tools,
at least two `COMPLETE_JOB_AD_HOC_SUB_PROCESS` instructions that drive the two
agent turns, and one `COMPLETE_JOB` instruction for each selected tool. Each
AHSP instruction selects the exact job type
`io.camunda.agenticai:aiagent:subprocess:2` (not element ID `AI_Agent`). Each
false completion must use an
`activateElements` array containing the exact tool element IDs whose jobs are
completed next; across the false completions, activate each of the four tools
exactly once. The first false/true AHSP pair drives two tools and finishes the
first turn; after feedback rejects that response, the second false/true pair
drives the other two tools and finishes the retry turn. Include
`COMPLETE_USER_TASK` first with `userSatisfied: false` and later `true`, then
`ASSERT_PROCESS_INSTANCE` with `state: "IS_COMPLETED"`. Do not use
`START_PROCESS`, top-level `processDefinitionId`, hyphen-only names, or empty
placeholder Java tests. Before running Maven, validate every JSON file with a
JSON parser and confirm its top-level `processId` and `testCases`.

Every AHSP instruction uses this shape. `activateElements` contains objects,
never bare strings, and is empty on a true completion:

```json
{{
  "type": "COMPLETE_JOB_AD_HOC_SUB_PROCESS",
  "jobSelector": {{
    "jobType": "io.camunda.agenticai:aiagent:subprocess:2"
  }},
  "completionConditionFulfilled": false,
  "activateElements": [
    {{"elementId": "ListUsers"}},
    {{"elementId": "Search_Recipe"}}
  ]
}}
```

Put all generated `.test.json` files directly under
`/workspace/test/src/test/resources/scenarios/`; `@TestCaseSource` does not
recurse into subdirectories.

Run the suite. After it passes, write `/workspace/report-summary.json` and:

- an interactive HTML report with BPMN completed-element/taken-flow
  highlighting and per-suite/per-scenario runs;
- a JSON summary with top-level `processCoverage`, `integrationCoverage`,
  `e2eOutcomes`, `suites`, and `redundancy`;
- exact reachable/covered element and sequence-flow totals;
- all four covered tool paths;
- named E2E outcomes;
- `redundancy.layers` entries for `deterministic`, `pointIntegration`, and
  `e2e`, each with `leaveOneOutApplied: true` and
  `redundantScenarios: []`, plus
  `redundancy.crossLayerOverlapExplanation`.

The JSON summary fields must use this exact shape and types:

```json
{{
  "processCoverage": {{
    "reachableElements": 1,
    "coveredElements": 1,
    "reachableSequenceFlows": 1,
    "coveredSequenceFlows": 1,
    "unreachableElements": []
  }},
  "integrationCoverage": {{
    "coveredTools": {json.dumps(sorted(TOOLS))},
    "totalPaths": 4
  }},
  "e2eOutcomes": ["Feedback journey — retry then approved outcome"],
  "suites": [
    {{"name": "deterministic", "runs": [{{"name": "scenario"}}]}},
    {{"name": "point integration", "runs": [{{"name": "scenario"}}]}},
    {{"name": "e2e", "runs": [{{"name": "scenario"}}]}}
  ],
  "redundancy": {{
    "layers": {{
      "deterministic": {{
        "leaveOneOutApplied": true,
        "redundantScenarios": []
      }},
      "pointIntegration": {{
        "leaveOneOutApplied": true,
        "redundantScenarios": []
      }},
      "e2e": {{
        "leaveOneOutApplied": true,
        "redundantScenarios": []
      }}
    }},
    "crossLayerOverlapExplanation": "Each layer proves a different contract."
  }}
}}
```

Write the HTML report specifically to
`/workspace/test/target/coverage-report/report.html`; it must contain
`window.COVERAGE_DATA` with suite and run data. As soon as tests pass, print
that exact absolute path. Do not stop before the implementation,
passing offline run, machine report, and HTML report all exist.

The task is not complete when Maven first passes. That only proves the runtime
suite. After Maven passes, you must create the machine and HTML reports, run
the full validator, and repair every failure. Before finishing, both commands
must pass:

```bash
python3 /workspace/generate-report-summary.py
python3 /workspace/validate-output.py
mvn -B -o -f /workspace/test/pom.xml test
```

Run `python3 /workspace/validate-output.py` as soon as the three scenario files
exist, before polishing documentation or adding any extra scenario. The early
scenario-only command is:

```bash
python3 /workspace/validate-output.py --scenarios-only
```

It identifies malformed instructions before the Maven run. Run the no-argument
validator only after the passing Maven run and generated reports; it validates
every remaining required artifact and report field.
Every `CREATE_PROCESS_INSTANCE` must include
`processDefinitionSelector.processDefinitionId`; every
`COMPLETE_USER_TASK` must select `User_Feedback`; every process assertion must
select `{PROCESS_ID}`. Every element assertion also requires that same
`processInstanceSelector`. A scenario cannot complete an active service task
or the AI Agent merely by asserting it: drive it with `COMPLETE_JOB` or
`COMPLETE_JOB_AD_HOC_SUB_PROCESS` first. Do not write coverage summaries or
reports from predicted results; derive them only after Maven has passed.

Once both validation commands pass, respond without a tool call with the
absolute HTML report path and a brief test result. Do not append a final `echo`,
file view, or status command.
"""


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
        dataset=[Sample(id=IMPLEMENTATION_SAMPLE, input=IMPLEMENTATION_PROMPT)],
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            artifact_scorer(),
            build_scorer(),
            process_coverage_scorer(),
            integration_path_scorer(),
            e2e_scorer(),
            isolation_scorer(),
            redundancy_scorer(),
            report_scorer(),
            report_handoff_scorer(),
            assert_skill_loaded("camunda-process-test", gating=False),
        ],
        sandbox=("docker", str(Path(__file__).with_name("compose.yaml"))),
        metadata=METADATA.model_dump(),
        time_limit=3600,
        token_limit=2_000_000,
        message_limit=140,
    )
