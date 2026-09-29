"""camunda-process-test outcome eval: executable three-layer agentic-process suite."""

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

PROCESS_ID = "ai-agent-chat-with-tools"
TOOLS = {"ListUsers", "Search_Recipe", "Jokes_API", "Activity_0x3prgn"}
FEEDBACK = "User_Feedback"


def _artifacts(state: TaskState) -> dict[str, str]:
    return {
        path: content
        for path, content in (state.store.get("artifacts") or {}).items()
        if isinstance(path, str) and isinstance(content, str)
    }


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
    for path, document in _json_documents(state):
        if {
            "processCoverage",
            "integrationCoverage",
            "e2eOutcomes",
            "suites",
            "redundancy",
        }.issubset(document):
            return path, document
    return None


@scorer(metrics=[mean(), stderr()])
def artifact_scorer() -> Scorer:
    """Require a runnable harness, separated layers, JSON intent, and live docs."""

    async def score(state: TaskState, target: Target) -> Score:
        files = _artifacts(state)
        cases = _test_cases(state)
        names = [case.get("name") for _, case in cases]
        failures = []
        if not any(path.endswith("pom.xml") for path in files):
            failures.append("missing Maven harness")
        if not any(
            path.endswith(".bpmn") and PROCESS_ID in text
            for path, text in files.items()
        ):
            failures.append("missing canonical BPMN")
        if not cases:
            failures.append("missing importable CPT JSON with top-level processId")
        if any(not isinstance(name, str) or " — " not in name for name in names):
            failures.append("scenario names must use '<who/what> — <outcome>'")
        corpus = "\n".join(f"{path}\n{text}" for path, text in files.items()).lower()
        layer_patterns = {
            "deterministic": r"\bdeterministic\b",
            "point integration": r"\bpoint[- ]integration\b",
            "e2e": r"\be2e\b|end[- ]to[- ]end",
        }
        for layer, pattern in layer_patterns.items():
            if not re.search(pattern, corpus):
                failures.append(f"missing separated {layer} artifact")
        if "live-dev" not in corpus and "live dev" not in corpus:
            failures.append("missing optional live-dev documentation")
        return Score(
            value=0.0 if failures else 1.0,
            explanation="; ".join(failures)
            or f"runnable three-layer harness with {len(cases)} JSON scenarios",
        )

    return score


@scorer(metrics=[mean(), stderr()])
def build_scorer() -> Scorer:
    """Run the generated default Maven suite in the network-disabled verifier."""

    async def score(state: TaskState, target: Target) -> Score:
        verifier = sandbox("verifier")
        prep = await verifier.exec(
            [
                "sh",
                "-c",
                "cp -R /agent-workspace/. /verifier-workspace/ "
                "&& find /verifier-workspace -name pom.xml -not -path '*/target/*' -print -quit",
            ],
            timeout=30,
        )
        pom = (prep.stdout or "").strip()
        if prep.returncode != 0 or not pom:
            return Score(value=0.0, explanation="generated Maven pom.xml not found")
        run = await verifier.exec(
            ["mvn", "-B", "-o", "-f", pom, "test"],
            timeout=900,
        )
        output = "\n".join(filter(None, [run.stdout, run.stderr]))
        lines = [
            line
            for line in output.splitlines()
            if "Tests run:" in line or "BUILD " in line or "[ERROR]" in line
        ]
        return Score(
            value=1.0 if run.returncode == 0 else 0.0,
            explanation="\n".join(lines[-30:]) or f"mvn exited {run.returncode}",
            metadata={"mvn_returncode": run.returncode, "raw_tail": output[-2000:]},
        )

    return score


@scorer(metrics=[mean(), stderr()])
def process_coverage_scorer() -> Scorer:
    """Require machine evidence for complete reachable element and flow coverage."""

    async def score(state: TaskState, target: Target) -> Score:
        found = _summary(state)
        if not found:
            return Score(
                value=0.0,
                explanation="missing combined machine-readable coverage summary",
            )
        path, data = found
        coverage = data["processCoverage"]
        required = (
            "reachableElements",
            "coveredElements",
            "reachableSequenceFlows",
            "coveredSequenceFlows",
        )
        if not isinstance(coverage, dict) or not all(
            isinstance(coverage.get(key), int) for key in required
        ):
            return Score(value=0.0, explanation="processCoverage totals are incomplete")
        complete = (
            coverage["reachableElements"] > 0
            and coverage["reachableElements"] == coverage["coveredElements"]
            and coverage["reachableSequenceFlows"] > 0
            and coverage["reachableSequenceFlows"] == coverage["coveredSequenceFlows"]
        )
        unreachable = coverage.get("unreachableElements", [])
        if unreachable and not coverage.get("bpmnDefectsReported"):
            complete = False
        return Score(
            value=1.0 if complete else 0.0,
            explanation=f"{path}: {coverage}",
        )

    return score


@scorer(metrics=[mean(), stderr()])
def integration_path_scorer() -> Scorer:
    """Require one isolated point-integration JSON scenario per canonical tool."""

    async def score(state: TaskState, target: Target) -> Score:
        covered = set()
        invalid = []
        for _, case in _test_cases(state):
            instructions = _instructions(case)
            start_ids = {
                start.get("elementId")
                for instruction in instructions
                for start in instruction.get("startInstructions", [])
                if isinstance(start, dict)
            }
            intended = start_ids & TOOLS
            if len(intended) != 1:
                continue
            tool = next(iter(intended))
            completed = any(
                instruction.get("state") == "IS_COMPLETED"
                and tool in _mentioned_elements({"instructions": [instruction]})
                for instruction in instructions
            )
            not_activated = {
                element
                for instruction in instructions
                if instruction.get("state") == "IS_NOT_ACTIVATED"
                for element in _mentioned_elements({"instructions": [instruction]})
            }
            expected_inactive = (TOOLS - {tool}) | {FEEDBACK}
            if completed and expected_inactive.issubset(not_activated):
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
    """Require a named full-process feedback/retry outcome reaching all tools."""

    async def score(state: TaskState, target: Target) -> Score:
        matches = []
        for _, case in _test_cases(state):
            instructions = _instructions(case)
            completion_values = [
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
            if (
                False in completion_values
                and True in completion_values
                and TOOLS.issubset(_mentioned_elements(case))
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
    """Reject mandatory-test code that calls public services, models, or credentials."""

    async def score(state: TaskState, target: Target) -> Score:
        suspicious = []
        for path, text in _artifacts(state).items():
            lower_path = path.lower()
            if (
                lower_path.endswith(".bpmn")
                or "live" in lower_path
                or lower_path.endswith(".md")
            ):
                continue
            if not lower_path.endswith(
                (".java", ".kt", ".yml", ".yaml", ".properties", ".xml")
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
            explanation="mandatory suite is credential-free and contains no public/model client calls"
            if not suspicious
            else "; ".join(suspicious),
        )

    return score


@scorer(metrics=[mean(), stderr()])
def redundancy_scorer() -> Scorer:
    """Require per-layer leave-one-out evidence and an overlap explanation."""

    async def score(state: TaskState, target: Target) -> Score:
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
    """Require machine and interactive suite/run-level report evidence."""

    async def score(state: TaskState, target: Target) -> Score:
        files = _artifacts(state)
        found = _summary(state)
        html = [
            (path, text)
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
        named_outcomes = (
            isinstance(outcomes, list)
            and bool(outcomes)
            and all(isinstance(outcome, (str, dict)) for outcome in outcomes)
        )
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
        return Score(
            value=1.0
            if found
            and html
            and valid_suites
            and integration_complete
            and named_outcomes
            else 0.0,
            explanation=(
                f"machine={found[0] if found else None} "
                f"html={[p for p, _ in html]} "
                f"suites={len(suites) if isinstance(suites, list) else 0} "
                f"integration={sorted(covered_tools)} e2e={len(outcomes) if isinstance(outcomes, list) else 0}"
            ),
        )

    return score


@scorer(metrics=[mean(), stderr()])
def report_handoff_scorer() -> Scorer:
    """Require the passing-run transcript to expose or open an absolute report path."""

    async def score(state: TaskState, target: Target) -> Score:
        transcript = "\n".join(
            str(getattr(message, "content", "")) for message in state.messages
        )
        for message in state.messages:
            for call in getattr(message, "tool_calls", None) or []:
                transcript += "\n" + json.dumps(call.arguments or {})
        path = re.search(r"/workspace/[^\s\"']*report[^\s\"']*\.html", transcript)
        opened = bool(re.search(r"\b(open|xdg-open|start)\b[^\n]*\.html", transcript))
        return Score(
            value=1.0 if path or opened else 0.0,
            explanation=f"report handoff path={path.group(0) if path else None}, opened={opened}",
        )

    return score


PROMPT = f"""
Build a complete Camunda Process Test harness for the canonical process at
`/fixture/ai-agent-chat-with-tools.bpmn`. Copy the BPMN into `/workspace`, put
the Maven harness under `/workspace/test`, and do not modify the process.
Use Spring Boot 4.0.0 and `camunda-process-test-spring` 8.9.5 so the sandbox's
offline Maven cache can resolve the build. The already-running local Camunda
runtime is available at `localhost:8080`; no Docker socket is available.

Create three separately identifiable layers that all run under the default
offline `mvn test` lifecycle:

1. Deterministic process tests: importable CPT JSON with top-level `processId`
   `{PROCESS_ID}` plus only the Java orchestration JSON cannot express. Mock the
   AI agent and connector jobs. Cover 100% of every reachable BPMN element and
   sequence flow, both gateway outcomes, feedback retry, a no-tool response,
   and all four tools: {", ".join(sorted(TOOLS))}.
2. Point integration: one isolated JSON scenario per tool. Start immediately at
   that tool with `startInstructions`, stop immediately after it, assert it
   completed, and assert the other three tools and `{FEEDBACK}` were not
   activated. Use local/mocked stable contracts only.
3. Mocked/local E2E: a named full-process business outcome that reaches all four
   expected tools without asserting order or response wording, rejects the first
   response with follow-up input, then approves and completes.

Every scenario name must use `<who/what> — <outcome>`. Apply leave-one-out
redundancy analysis within each layer and explain why cross-layer overlap is
valid. Treat unreachable elements as reported BPMN defects, never silent
exclusions. Document a separate optional `live-dev` profile; it must not run by
default.

After tests pass, produce an interactive HTML report with BPMN highlighting and
a machine-readable JSON summary containing these top-level keys:
`processCoverage`, `integrationCoverage`, `e2eOutcomes`, `suites`, and
`redundancy`. Process coverage must give reachable/covered element and sequence
flow integer totals. Integration coverage must enumerate all four tools. Each
of the three suites must contain scenario-level `runs`. Redundancy must contain
`layers.deterministic`, `layers.pointIntegration`, and `layers.e2e`, each with
`leaveOneOutApplied: true` and `redundantScenarios: []`, plus a
`crossLayerOverlapExplanation`.

Run `mvn test` yourself with no external network, SaaS credentials, public APIs,
or real LLM. As soon as it passes, try to open the HTML report if this
environment supports it; otherwise print its absolute `/workspace/...` path.
Do not stop before the harness, reports, and passing test run exist.
"""

SAMPLES = [Sample(id="agentic-three-layer-suite", input=PROMPT)]


@task
def camunda_process_test(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        solver=with_artifact_collection(build_agent(agent, skill_dirs)),
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
        time_limit=1800,
        token_limit=700_000,
        message_limit=80,
    )
