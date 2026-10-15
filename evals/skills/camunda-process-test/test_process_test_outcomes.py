from __future__ import annotations

import asyncio
import importlib.util
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


def _optional_score(markdown: str, sample_id: str = _outcomes.SPEC_SAMPLE) -> float:
    state = SimpleNamespace(
        store={"artifacts": {_outcomes.SPEC_PATH: markdown}},
        messages=[],
        sample_id=sample_id,
    )
    return asyncio.run(_outcomes.test_spec_optional()(state, None)).value


def _complete_spec() -> str:
    return """
# Agent process test plan

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
| PI-1 | `process-integration/retry` | The exact unordered tool set activates; unrelated tools remain inactive; approval completes. |
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
Handoff: provide the exact report paths after required checks pass.

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
Handoff: provide the exact report paths after required checks pass.

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
| M-1 | Review order | A reviewer observes readable fields and completes review. |

## Run and inspect
Prerequisites: Java, Maven, and a local payment stub.
Run `mvn test`; perform the required manual form check separately.
Live network and credential execution is optional.
Reports: interactive HTML `target/report.html`; machine JSON `target/report.json`.
Handoff: provide the exact report paths after required checks pass.

## Artifacts
- [BPMN](./order.bpmn)
- [Plan](./TESTING.md)
- [Tests](./test/)

## Approval
Status: DRAFT
Open decisions: manual-check owner.
Do not implement tests before implementation approval.
"""


def test_complete_markdown_spec_passes() -> None:
    assert _score(_complete_spec()) == 1.0


def test_missing_approval_gate_fails() -> None:
    spec = (
        _complete_spec()
        .replace("Status: DRAFT", "")
        .replace("Do not implement tests before implementation approval.", "")
    )
    assert _score(spec) == 0.0


def test_placeholder_artifact_links_fail() -> None:
    assert (
        _score(_complete_spec().replace("[BPMN](./process.bpmn)", "[BPMN](#)")) == 0.0
    )


def test_missing_report_handoff_fails() -> None:
    assert (
        _score(
            _complete_spec().replace(
                "Handoff: provide the exact report paths after required checks pass.",
                "",
            )
        )
        == 0.0
    )


def test_simple_process_selects_only_process_and_manual_suites() -> None:
    assert _score(_simple_spec(), _outcomes.SIMPLE_SPEC_SAMPLE) == 1.0
    irrelevant = """
## Segment integration tests
- **Verifies:** Nothing distinct.
- **Required evidence:** All paths.
- **Mocks:** None.
| ID | Test | Guarantee |
|---|---|---|
| S-1 | `segment/none` | A nonexistent connector returns data. |
"""
    invalid = _simple_spec().replace(
        "## Manual tests", irrelevant + "\n## Manual tests"
    )
    assert _score(invalid, _outcomes.SIMPLE_SPEC_SAMPLE) == 0.0


def test_connector_selects_segment_without_process_integration() -> None:
    assert _score(_connector_spec(), _outcomes.CONNECTOR_SPEC_SAMPLE) == 1.0


def test_optional_quality_does_not_weaken_required_gate() -> None:
    weakened = _connector_spec().replace(
        "Test Studio choice: use stronger managed native CPT for receipt shape and\n"
        "visible importable scenarios for routing. This hybrid retains the shape\n"
        "guarantee; variable presence alone would reduce it and does not prove non-empty\n"
        "content.\n",
        "",
    )
    assert _score(weakened, _outcomes.CONNECTOR_SPEC_SAMPLE) == 1.0
    assert _optional_score(weakened, _outcomes.CONNECTOR_SPEC_SAMPLE) < 1.0


def test_overall_score_weights_required_above_optional() -> None:
    state = SimpleNamespace(
        store={"artifacts": {_outcomes.SPEC_PATH: _complete_spec()}},
        messages=[],
        sample_id=_outcomes.SPEC_SAMPLE,
    )
    score = asyncio.run(_outcomes.test_spec_overall()(state, None))
    assert score.value == 1.0
    assert score.metadata == {"required": 1.0, "optional": 1.0}


def test_task_registers_three_spec_samples_without_changing_scenario_task() -> None:
    spec_task = _outcomes.camunda_process_test_spec()
    scenario_task = _outcomes.camunda_process_test()

    assert [sample.id for sample in spec_task.dataset] == [
        "agentic-test-specification",
        "connector-user-task-test-specification",
        "simple-user-task-test-specification",
    ]
    assert [sample.id for sample in scenario_task.dataset] == [
        "invoice-approval-two-outcomes"
    ]
    assert "write only `/workspace/TESTING.md`" in spec_task.dataset[0].input
    assert str(spec_task.sandbox.config).endswith(
        "camunda-process-test/compose-spec.yaml"
    )
