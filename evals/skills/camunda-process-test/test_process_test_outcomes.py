from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _load_outcomes() -> ModuleType:
    path = Path(__file__).with_name("outcomes.py")
    spec = importlib.util.spec_from_file_location("camunda_process_test_outcomes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_outcomes = _load_outcomes()


def _integration_case(tool: str) -> dict:
    inactive = sorted((_outcomes.TOOLS - {tool}) | {_outcomes.FEEDBACK})
    return {
        "name": f"{tool} — stable point integration contract",
        "instructions": [
            {
                "type": "CREATE_PROCESS_INSTANCE",
                "startInstructions": [{"elementId": tool}],
            },
            {
                "type": "ASSERT_ELEMENT_INSTANCE",
                "elementSelector": {"elementId": tool},
                "state": "IS_COMPLETED",
            },
            {
                "type": "ASSERT_ELEMENT_INSTANCES",
                "elementSelectors": [{"elementId": value} for value in inactive],
                "state": "IS_NOT_ACTIVATED",
            },
        ],
    }


def _state(*, omit_tool: str | None = None) -> SimpleNamespace:
    integration_cases = [
        _integration_case(tool) for tool in sorted(_outcomes.TOOLS - {omit_tool})
    ]
    e2e = {
        "name": "Feedback journey — retry then approved outcome",
        "instructions": [
            *[
                {
                    "type": "ASSERT_ELEMENT_INSTANCE",
                    "elementSelector": {"elementId": tool},
                    "state": "IS_COMPLETED",
                }
                for tool in sorted(_outcomes.TOOLS)
            ],
            {
                "type": "COMPLETE_USER_TASK",
                "variables": {"userSatisfied": False},
            },
            {
                "type": "COMPLETE_USER_TASK",
                "variables": {"userSatisfied": True},
            },
            {"type": "ASSERT_PROCESS_INSTANCE", "state": "IS_COMPLETED"},
        ],
    }
    summary = {
        "processCoverage": {
            "reachableElements": 10,
            "coveredElements": 10,
            "reachableSequenceFlows": 9,
            "coveredSequenceFlows": 9,
            "unreachableElements": [],
        },
        "integrationCoverage": {
            "coveredTools": sorted(_outcomes.TOOLS),
            "totalPaths": 4,
        },
        "e2eOutcomes": ["retry then approved"],
        "suites": [
            {"name": "deterministic", "runs": [{}]},
            {"name": "point integration", "runs": [{}]},
            {"name": "e2e", "runs": [{}]},
        ],
        "redundancy": {
            "layers": {
                layer: {
                    "leaveOneOutApplied": True,
                    "redundantScenarios": [],
                }
                for layer in ("deterministic", "pointIntegration", "e2e")
            },
            "crossLayerOverlapExplanation": "Each layer proves a different contract.",
        },
    }
    artifacts = {
        "/workspace/process.bpmn": '<bpmn:process id="ai-agent-chat-with-tools"/>',
        "/workspace/test/pom.xml": "<project/>",
        "/workspace/test/README.md": (
            "deterministic; point-integration; E2E; optional live-dev profile"
        ),
        "/workspace/test/process.test.json": json.dumps(
            {
                "processId": _outcomes.PROCESS_ID,
                "testCases": [
                    {
                        "name": "Direct answer — no tools required",
                        "instructions": [],
                    }
                ],
            }
        ),
        "/workspace/test/integration.test.json": json.dumps(
            {"processId": _outcomes.PROCESS_ID, "testCases": integration_cases}
        ),
        "/workspace/test/e2e.test.json": json.dumps(
            {"processId": _outcomes.PROCESS_ID, "testCases": [e2e]}
        ),
        "/workspace/test/target/coverage-summary.json": json.dumps(summary),
        "/workspace/test/target/coverage-report/report.html": (
            "<script>window.COVERAGE_DATA={completedElements:[]}</script>"
        ),
    }
    return SimpleNamespace(store={"artifacts": artifacts}, messages=[])


def _score(scorer, state) -> float:
    return asyncio.run(scorer(state, None)).value


def test_complete_three_layer_artifacts_pass_static_scorers() -> None:
    state = _state()

    for factory in (
        _outcomes.artifact_scorer,
        _outcomes.process_coverage_scorer,
        _outcomes.integration_path_scorer,
        _outcomes.e2e_scorer,
        _outcomes.isolation_scorer,
        _outcomes.redundancy_scorer,
        _outcomes.report_scorer,
    ):
        assert _score(factory(), state) == 1.0, factory.__name__


def test_point_integration_requires_every_canonical_tool() -> None:
    assert (
        _score(_outcomes.integration_path_scorer(), _state(omit_tool="Jokes_API"))
        == 0.0
    )


def test_task_uses_executable_canonical_sample() -> None:
    task = _outcomes.camunda_process_test()

    assert [sample.id for sample in task.dataset] == ["agentic-three-layer-suite"]
    assert str(task.sandbox.config).endswith("camunda-process-test/compose.yaml")
