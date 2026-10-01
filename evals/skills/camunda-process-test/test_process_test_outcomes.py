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


def _score(markdown: str, sample_id: str = _outcomes.SPEC_SAMPLE) -> float:
    state = SimpleNamespace(
        store={"artifacts": {_outcomes.SPEC_PATH: markdown}},
        messages=[],
        sample_id=sample_id,
    )
    return asyncio.run(_outcomes.test_spec_complete()(state, None)).value


def _optional_score(
    markdown: str, sample_id: str = _outcomes.SPEC_SAMPLE
) -> float:
    state = SimpleNamespace(
        store={"artifacts": {_outcomes.SPEC_PATH: markdown}},
        messages=[],
        sample_id=sample_id,
    )
    return asyncio.run(_outcomes.test_spec_optional()(state, None)).value


def _complete_spec() -> str:
    return """
# Agent process test plan

The suites prove routing, isolated contracts, business outcomes, and observed behavior.

## Process tests
- **Verifies:** Routing.
- **Required evidence:** 100% of reachable elements and flows.
- **Mocks:** All external systems.
| ID | Test | Guarantee |
|---|---|---|
| P-1 | `process/retry` | Rejected feedback routes to retry; approval completes. |

## Segment integration tests
- **Verifies:** Stable tool contracts.
- **Required evidence:** All tool paths pass.
- **Mocks:** Local dependencies replace public services.
| ID | Test | Guarantee |
|---|---|---|
| S-1 | `segment/tool` | Each isolated tool returns its required shape. |
**Limitation:** A live worker may execute before cancellation and cause a side effect.

## Process integration tests
- **Verifies:** Named whole-process outcomes.
- **Required evidence:** 3/3 automated outcomes pass.
- **Mocks:** Local dependencies.
- **Boundary:** External-system impacts are not verified.
| ID | Test | Guarantee |
|---|---|---|
| PI-1 | `process-integration/retry` | The expected unordered tool set activates and later approval completes. |
Tool sets are unordered; exact generated wording is not asserted.
Test Studio choice: use a hybrid. Visible scenarios retain routing evidence;
managed native CPT retains the full non-empty shape guarantee. Variable
presence alone is weaker and does not prove shape, non-empty content, or
exclusivity.

## Manual tests
- **Verifies:** Human-observed behavior.
- **Required evidence:** 1/1 policy-required check passes.
- **Mocks:** None.
| ID | Test | Guarantee |
|---|---|---|
| M-1 | Review journey | A person observes a usable response and completes approval. |

## Run and inspect
Prerequisites: Java, Maven, Docker, and local fixtures.
Run `mvn test`; live model/network execution is optional.
Reports: interactive HTML `target/report.html`; machine JSON `target/report.json`.

## Artifacts
- [BPMN](./process.bpmn)
- [Plan](./TESTING.md)
- [Tests](./test/)

## Approval
Status: DRAFT
Open decisions: live dependencies.
Do not implement tests before implementation approval.
"""


def _simple_spec() -> str:
    return """
# Approval test plan

Process tests prove routing; manual tests cover the human form experience.

## Process tests
- **Verifies:** Both decisions and end states.
- **Required evidence:** 100% of reachable elements and flows.
- **Mocks:** None.
| ID | Test | Guarantee |
|---|---|---|
| P-1 | `process/approved` | Approval routes to the approved end state. |
| P-2 | `process/rejected` | Rejection routes to the rejected end state. |

## Manual tests
- **Verifies:** User-task form look and feel.
- **Required evidence:** 1/1 policy-required usability check passes.
- **Mocks:** None.
| ID | Test | Guarantee |
|---|---|---|
| M-1 | Review form | A reviewer observes readable fields and completes the task. |

## Run and inspect
Prerequisites: Java and Maven.
Run `mvn test`; perform the required manual form check separately.
Reports: interactive HTML `target/report.html`; machine JSON `target/report.json`.

## Artifacts
- [BPMN](./approval.bpmn)
- [Plan](./TESTING.md)
- [Tests](./test/)

## Approval
Status: DRAFT
Open decisions: manual-check owner.
Do not implement tests before implementation approval.
"""


def _connector_spec() -> str:
    return """
# Order approval test plan

The suites prove process routing, payment contract isolation, and review usability.

## Process tests
- **Verifies:** Approval and rejection routing.
- **Required evidence:** 100% of reachable elements and flows.
- **Mocks:** The payment boundary is mocked.
| ID | Test | Guarantee |
|---|---|---|
| P-1 | `process/approved` | Approval reaches the approved end state. |
| P-2 | `process/rejected` | Rejection reaches the rejected end state. |

## Segment integration tests
- **Verifies:** The stable payment response contract.
- **Required evidence:** All payment contract fields pass validation.
- **Mocks:** A local payment stub replaces the public service.
| ID | Test | Guarantee |
|---|---|---|
| S-1 | `segment/payment` | Payment returns a success status and receipt identifier. |
**Boundary:** External financial impact is not verified.
Test Studio choice: use stronger managed native CPT for receipt shape and
visible importable scenarios for routing. This hybrid retains the shape
guarantee; variable presence alone would reduce it and does not prove non-empty
content.

## Manual tests
- **Verifies:** Human review form look and feel.
- **Required evidence:** 1/1 policy-required usability check passes.
- **Mocks:** None.
| ID | Test | Guarantee |
|---|---|---|
| M-1 | Review order | A reviewer observes readable order fields and completes review. |

## Run and inspect
Prerequisites: Java, Maven, and a local payment stub.
Run `mvn test`; perform the required manual form check separately.
Live network and credential execution is optional.
Reports: interactive HTML `target/report.html`; machine JSON `target/report.json`.

## Artifacts
- [BPMN](./order.bpmn)
- [Plan](./TESTING.md)
- [Tests](./test/)

## Approval
Status: DRAFT
Open decisions: manual-check owner.
Do not implement tests before implementation approval.
"""


def _integration_case(tool: str) -> dict:
    inactive = sorted((_outcomes.TOOLS - {tool}) | {_outcomes.FEEDBACK})
    return {
        "name": f"{tool} — stable point integration contract",
        "instructions": [
            {
                "type": "CREATE_PROCESS_INSTANCE",
                "processDefinitionSelector": {
                    "processDefinitionId": _outcomes.PROCESS_ID
                },
            },
            {
                "type": "COMPLETE_JOB_AD_HOC_SUB_PROCESS",
                "jobSelector": {
                    "jobType": "io.camunda.agenticai:aiagent:subprocess:2"
                },
                "completionConditionFulfilled": False,
                "activateElements": [{"elementId": tool}],
            },
            {
                "type": "COMPLETE_JOB",
                "jobSelector": {"elementId": tool},
                "variables": {"toolCallResult": {}},
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


def _implementation_state(*, omit_tool: str | None = None) -> SimpleNamespace:
    integration_cases = [
        _integration_case(tool) for tool in sorted(_outcomes.TOOLS - {omit_tool})
    ]
    e2e = {
        "name": "Feedback journey — retry then approved outcome",
        "instructions": [
            {
                "type": "COMPLETE_JOB_AD_HOC_SUB_PROCESS",
                "jobSelector": {"elementId": "AI_Agent"},
                "completionConditionFulfilled": False,
            },
            {
                "type": "COMPLETE_JOB_AD_HOC_SUB_PROCESS",
                "jobSelector": {"elementId": "AI_Agent"},
                "completionConditionFulfilled": True,
            },
            {
                "type": "COMPLETE_JOB_AD_HOC_SUB_PROCESS",
                "jobSelector": {"elementId": "AI_Agent"},
                "completionConditionFulfilled": False,
            },
            {
                "type": "COMPLETE_JOB_AD_HOC_SUB_PROCESS",
                "jobSelector": {"elementId": "AI_Agent"},
                "completionConditionFulfilled": True,
            },
            *[
                {
                    "type": "COMPLETE_JOB",
                    "jobSelector": {"elementId": tool},
                }
                for tool in sorted(_outcomes.TOOLS)
            ],
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
        _outcomes.SPEC_PATH: "# Test specification\n\nStatus: APPROVED",
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
    return SimpleNamespace(
        store={"artifacts": artifacts},
        messages=[
            SimpleNamespace(
                role="assistant",
                content=(
                    "Report: /workspace/test/target/coverage-report/report.html"
                ),
                tool_calls=[],
            )
        ],
        sample_id=_outcomes.IMPLEMENTATION_SAMPLE,
    )


def test_complete_markdown_spec_passes() -> None:
    assert _score(_complete_spec()) == 1.0


def test_missing_approval_gate_fails() -> None:
    assert (
        _score(
            _complete_spec()
            .replace("Status: DRAFT", "")
            .replace("Do not implement tests before implementation approval.", "")
        )
        == 0.0
    )


def test_placeholder_artifact_links_fail() -> None:
    assert (
        _score(
            _complete_spec().replace(
                "[BPMN](./process.bpmn)",
                "[BPMN](#)",
            )
        )
        == 0.0
    )


def test_simple_process_omits_irrelevant_integration_suites() -> None:
    assert _score(_simple_spec(), _outcomes.SIMPLE_SPEC_SAMPLE) == 1.0


def test_simple_process_rejects_irrelevant_integration_suite() -> None:
    irrelevant = """
## Segment integration tests
- **Verifies:** Nothing distinct.
- **Required evidence:** All paths.
- **Mocks:** None.
| ID | Test | Guarantee |
|---|---|---|
| S-1 | `segment/none` | A nonexistent connector returns data. |
"""

    assert (
        _score(
            _simple_spec().replace("## Manual tests", irrelevant + "\n## Manual tests"),
            _outcomes.SIMPLE_SPEC_SAMPLE,
        )
        == 0.0
    )


def test_connector_process_selects_segment_without_process_integration() -> None:
    assert _score(_connector_spec(), _outcomes.CONNECTOR_SPEC_SAMPLE) == 1.0


def test_connector_process_rejects_silent_assertion_weakening() -> None:
    weakened = _connector_spec().replace(
        "Test Studio choice: use stronger managed native CPT for receipt shape and\n"
        "visible importable scenarios for routing. This hybrid retains the shape\n"
        "guarantee; variable presence alone would reduce it and does not prove non-empty\n"
        "content.\n",
        "",
    )

    assert _score(weakened, _outcomes.CONNECTOR_SPEC_SAMPLE) == 1.0
    assert _optional_score(weakened, _outcomes.CONNECTOR_SPEC_SAMPLE) < 1.0


def test_overall_spec_score_weights_required_above_optional() -> None:
    state = SimpleNamespace(
        store={"artifacts": {_outcomes.SPEC_PATH: _complete_spec()}},
        messages=[],
        sample_id=_outcomes.SPEC_SAMPLE,
    )

    score = asyncio.run(_outcomes.test_spec_overall()(state, None))

    assert score.value == 1.0
    assert score.metadata == {"required": 1.0, "optional": 1.0}


def test_complete_three_layer_artifacts_pass_static_scorers() -> None:
    state = _implementation_state()

    for factory in (
        _outcomes.artifact_scorer,
        _outcomes.process_coverage_scorer,
        _outcomes.integration_path_scorer,
        _outcomes.e2e_scorer,
        _outcomes.isolation_scorer,
        _outcomes.redundancy_scorer,
        _outcomes.report_scorer,
        _outcomes.report_handoff_scorer,
    ):
        assert asyncio.run(factory()(state, None)).value == 1.0, factory.__name__


def test_point_integration_requires_every_canonical_tool() -> None:
    state = _implementation_state(omit_tool="Jokes_API")

    assert asyncio.run(_outcomes.integration_path_scorer()(state, None)).value == 0.0


def test_report_handoff_rejects_placeholder_path() -> None:
    state = _implementation_state()
    state.messages[0].content = "Report: /workspace/...report...html"

    assert asyncio.run(_outcomes.report_handoff_scorer()(state, None)).value == 0.0


def test_report_handoff_ignores_path_in_user_prompt() -> None:
    state = _implementation_state()
    state.messages = [
        SimpleNamespace(
            role="user",
            content="Print /workspace/test/target/coverage-report/report.html",
            tool_calls=[],
        )
    ]

    assert asyncio.run(_outcomes.report_handoff_scorer()(state, None)).value == 0.0


def test_scorers_apply_only_to_their_stage() -> None:
    spec_state = SimpleNamespace(
        store={"artifacts": {_outcomes.SPEC_PATH: _complete_spec()}},
        messages=[],
        sample_id=_outcomes.SPEC_SAMPLE,
    )
    implementation_state = _implementation_state()

    assert (
        asyncio.run(_outcomes.artifact_scorer()(spec_state, None)).metadata[
            "not_applicable"
        ]
        is True
    )
    assert (
        asyncio.run(
            _outcomes.test_spec_complete()(implementation_state, None)
        ).metadata["not_applicable"]
        is True
    )


def test_task_requests_spec_then_approved_implementation() -> None:
    spec_task = _outcomes.camunda_process_test_spec()
    implementation_task = _outcomes.camunda_process_test()

    assert [sample.id for sample in spec_task.dataset] == [
        "agentic-test-specification",
        "connector-user-task-test-specification",
        "simple-user-task-test-specification",
    ]
    assert [sample.id for sample in implementation_task.dataset] == [
        "agentic-three-layer-suite"
    ]
    assert "write only `/workspace/TESTING.md`" in spec_task.dataset[0].input
    assert "approved `/fixture/TESTING.md`" in implementation_task.dataset[0].input
    assert str(spec_task.sandbox.config).endswith(
        "camunda-process-test/compose-spec.yaml"
    )
    assert str(implementation_task.sandbox.config).endswith(
        "camunda-process-test/compose.yaml"
    )
