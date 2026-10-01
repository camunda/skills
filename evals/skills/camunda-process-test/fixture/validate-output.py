#!/usr/bin/env python3
"""Fast structural preflight for the generated canonical CPT eval artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/workspace")
TEST = ROOT / "test"
TOOLS = {"ListUsers", "Search_Recipe", "Jokes_API", "Activity_0x3prgn"}
AGENT_JOB_TYPE = "io.camunda.agenticai:aiagent:subprocess:2"


def load(path: Path) -> dict:
    value = json.loads(path.read_text())
    assert isinstance(value, dict), f"{path}: top level must be an object"
    return value


assert (ROOT / "TESTING.md").read_bytes() == Path("/fixture/TESTING.md").read_bytes()
assert sorted(ROOT.rglob("pom.xml")) == [TEST / "pom.xml"]
assert (TEST / "pom.xml").read_bytes() == Path("/fixture/pom.xml").read_bytes()
java_root = TEST / "src/test/java/io/camunda/tests"
for name in ("ProcessTest.java", "TestApplication.java"):
    assert (java_root / name).read_bytes() == Path(f"/fixture/{name}").read_bytes()
assert sorted(path.name for path in java_root.glob("*.java")) == [
    "ProcessTest.java",
    "TestApplication.java",
], "do not add Java test classes"

scenario_root = TEST / "src/test/resources/scenarios"
scenario_paths = sorted(scenario_root.glob("*.test.json"))
assert [path.name for path in scenario_paths] == [
    "deterministic.test.json",
    "e2e.test.json",
    "point-integration.test.json",
]

cases_by_file = {}
for path in scenario_paths:
    document = load(path)
    assert document.get("processId") == "ai-agent-chat-with-tools", path
    assert isinstance(document.get("testCases"), list), path
    cases_by_file[path.name] = document["testCases"]

cases = [case for file_cases in cases_by_file.values() for case in file_cases]
assert cases, "no CPT test cases"
assert all(" — " in case.get("name", "") for case in cases), "invalid scenario name"

for case in cases:
    latest_ahsp_completion = None
    for instruction in case.get("instructions", []):
        instruction_type = instruction.get("type")
        if instruction_type == "CREATE_PROCESS_INSTANCE":
            assert instruction.get("processDefinitionSelector") == {
                "processDefinitionId": "ai-agent-chat-with-tools"
            }, f"{case['name']}: invalid process selector"
            assert all(
                start.get("elementId") != "StartEvent_1"
                for start in instruction.get("startInstructions", [])
                if isinstance(start, dict)
            ), f"{case['name']}: do not target the start event"
        if instruction_type in {
            "ASSERT_ELEMENT_INSTANCE",
            "ASSERT_ELEMENT_INSTANCES",
            "ASSERT_PROCESS_INSTANCE",
        }:
            assert instruction.get("processInstanceSelector") == {
                "processDefinitionId": "ai-agent-chat-with-tools"
            }, f"{case['name']}: assertion lacks process instance selector"
        if instruction_type == "COMPLETE_USER_TASK":
            assert instruction.get("userTaskSelector", {}).get("elementId") == (
                "User_Feedback"
            ), f"{case['name']}: invalid feedback selector"
            assert latest_ahsp_completion is True, (
                f"{case['name']}: finish the agent turn before feedback"
            )
        if instruction_type == "COMPLETE_JOB_AD_HOC_SUB_PROCESS":
            assert isinstance(
                instruction.get("completionConditionFulfilled"), bool
            ), f"{case['name']}: AHSP completion flag must be boolean"
            assert (
                instruction.get("jobSelector", {}).get("jobType") == AGENT_JOB_TYPE
            ), f"{case['name']}: invalid AHSP selector"
            activations = instruction.get("activateElements", [])
            assert isinstance(activations, list) and all(
                isinstance(activation, dict)
                and activation.get("elementId") in TOOLS
                for activation in activations
            ), f"{case['name']}: invalid AHSP activateElements"
            latest_ahsp_completion = instruction["completionConditionFulfilled"]

covered = set()
for case in cases_by_file["point-integration.test.json"]:
    instructions = case.get("instructions", [])
    activated = {
        activation.get("elementId")
        for instruction in instructions
        if instruction.get("type") == "COMPLETE_JOB_AD_HOC_SUB_PROCESS"
        and instruction.get("completionConditionFulfilled") is False
        for activation in instruction.get("activateElements", [])
        if isinstance(activation, dict)
    }
    intended = activated & TOOLS
    if len(intended) != 1:
        continue
    tool = next(iter(intended))
    text = json.dumps(instructions)
    if (
        any(
            instruction.get("type") == "COMPLETE_JOB"
            and instruction.get("jobSelector", {}).get("elementId") == tool
            for instruction in instructions
        )
        and
        '"state": "IS_COMPLETED"' in text
        and '"state": "IS_NOT_ACTIVATED"' in text
        and all(value in text for value in (TOOLS - {tool}) | {"User_Feedback"})
    ):
        covered.add(tool)
assert covered == TOOLS, f"isolated tool coverage: {sorted(covered)}"

e2e = [
    case
    for case in cases_by_file["e2e.test.json"]
    if TOOLS.issubset(set(json.dumps(case).split('"')))
    and sum(
        instruction.get("type") == "COMPLETE_JOB_AD_HOC_SUB_PROCESS"
        for instruction in case.get("instructions", [])
    )
    >= 2
    and TOOLS.issubset(
        {
            instruction.get("jobSelector", {}).get("elementId")
            for instruction in case.get("instructions", [])
            if instruction.get("type") == "COMPLETE_JOB"
        }
    )
    and '"userSatisfied": false' in json.dumps(case)
    and '"userSatisfied": true' in json.dumps(case)
    and '"type": "ASSERT_PROCESS_INSTANCE"' in json.dumps(case)
    and '"state": "IS_COMPLETED"' in json.dumps(case)
]
assert e2e, "missing retry-then-approve E2E case"
for case in e2e:
    instructions = case["instructions"]
    activations = {
        activation.get("elementId")
        for instruction in instructions
        if instruction.get("type") == "COMPLETE_JOB_AD_HOC_SUB_PROCESS"
        and instruction.get("completionConditionFulfilled") is False
        for activation in instruction.get("activateElements", [])
    }
    completed_jobs = {
        instruction.get("jobSelector", {}).get("elementId")
        for instruction in instructions
        if instruction.get("type") == "COMPLETE_JOB"
    }
    assert activations == TOOLS, (
        f"{case['name']}: AHSP tool activations must equal {sorted(TOOLS)}"
    )
    assert completed_jobs == TOOLS, (
        f"{case['name']}: completed tool jobs must equal {sorted(TOOLS)}"
    )

if "--scenarios-only" in sys.argv:
    print("scenario structure valid")
    raise SystemExit(0)

summary = load(ROOT / "report-summary.json")
coverage = summary["processCoverage"]
assert coverage["reachableElements"] == coverage["coveredElements"] > 0
assert (
    coverage["reachableSequenceFlows"] == coverage["coveredSequenceFlows"] > 0
)
integration = summary["integrationCoverage"]
assert set(integration["coveredTools"]) == TOOLS
assert integration["totalPaths"] == 4
assert summary["e2eOutcomes"]
assert len(summary["suites"]) >= 3
assert all(suite.get("runs") for suite in summary["suites"])
redundancy = summary["redundancy"]
for layer in ("deterministic", "pointIntegration", "e2e"):
    assert redundancy["layers"][layer] == {
        "leaveOneOutApplied": True,
        "redundantScenarios": [],
    }
assert redundancy["crossLayerOverlapExplanation"]

report = TEST / "target/coverage-report/report.html"
assert "window.COVERAGE_DATA" in report.read_text()
print("output structure valid")
