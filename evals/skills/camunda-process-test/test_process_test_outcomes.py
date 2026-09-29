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


def _score(markdown: str) -> float:
    state = SimpleNamespace(
        store={"artifacts": {_outcomes.SPEC_PATH: markdown}},
        messages=[],
    )
    return asyncio.run(_outcomes.test_spec_complete()(state, None)).value


def _complete_spec() -> str:
    return """
# Testing and acceptance criteria

## High-level testing strategy
| Layer | Purpose | External systems | Acceptance signal | Run |
| Process | Routing | Mocked | Coverage | Every push |
| Segment integration | Contract | Local stubs | Tool path | On demand |
| Process integration | Business outcome | Local/live profile | Named E2E | Scheduled |

## Requirements traceability
| ID | Requirement | Layer | Scenario | Evidence | Status | Comment |
| PR-1 | Completes | Process | happy | terminal | planned | — |
| PR-2 | Retries | Process | retry | loop | planned | — |
| PR-3 | No tool | Process | answer | path | planned | — |
| SIR-1 | Users | Segment | ListUsers | shape | planned | — |
| SIR-2 | Recipe | Segment | Search_Recipe | shape | planned | — |
| SIR-3 | Joke | Segment | Jokes_API | shape | planned | — |
| SIR-4 | Tech | Segment | Activity_0x3prgn | shape | planned | — |
| PIR-1 | Journey | Process integration | feedback | outcome | planned | — |
Assertion philosophy: prove requirements. Exact prose and UI are out of scope.

## Coverage thresholds
| Layer | Target | Gate | Report | Rationale |
| Process | 100% | 100% | report.json | all routing |
| Segment | 100% | 100% | contracts.json | all tools |
| Integration | 100% | 80% | junit | realistic paths |
Thresholds are user-tunable and require approval.

## End-to-end scenarios
| # | Scenario | Expected outcome | Terminal element | Expected tools | Requirement |
| 1 | Ask for users | Answer | Event_0i39jej | ListUsers | PIR-1 |
| 2 | Ask for recipe | Answer | Event_0i39jej | Search_Recipe | PIR-1 |
| 3 | Reject first result, provide follow-up, then approve satisfied result | Complete | Event_0i39jej | Jokes_API, Activity_0x3prgn | PIR-1 |
No tool order assertion. Retry unexpected model routing once.

## How to run
Process: `mvn test`. Integration: `mvn test -P integration-test`.
E2E: `mvn test -P e2e`.
Prerequisites: Java, Maven, Docker. Reports: `target/coverage-report/report.html`.

## Artifacts and links
| Artifact | Link |
| BPMN | [source BPMN](./ai-agent-chat-with-tools.bpmn) |
| Spec | [this test spec](./TESTING.md) |
| CPT docs | [Camunda Process Test](https://docs.camunda.io/docs/apis-tools/testing/) |
| Planned tests | [planned scenarios](./test/src/test/resources/scenarios/) |

## Approval and open questions
Status: DRAFT. Approval required before implementation. Do not implement tests
until the user approves requirements, scenarios, dependencies, and thresholds.
Open question: which live endpoints are allowed? Decision needed: CI cadence.
"""


def test_complete_markdown_spec_passes() -> None:
    assert _score(_complete_spec()) == 1.0


def test_missing_approval_gate_fails() -> None:
    assert (
        _score(
            _complete_spec()
            .replace("Approval required before implementation.", "")
            .replace(
                "Do not implement tests\nuntil the user approves requirements, scenarios, dependencies, and thresholds.",
                "",
            )
        )
        == 0.0
    )


def test_placeholder_artifact_links_fail() -> None:
    assert (
        _score(
            _complete_spec().replace(
                "[source BPMN](./ai-agent-chat-with-tools.bpmn)",
                "[source BPMN](#)",
            )
        )
        == 0.0
    )


def test_reference_qwen_benchmark_passes() -> None:
    benchmark = (
        Path(__file__).parent
        / "benchmarks/qwen3-coder-30b/2026-09-29T21-34-03Z/TESTING.md"
    )

    assert _score(benchmark.read_text()) == 1.0


def test_task_requests_one_markdown_artifact() -> None:
    task = _outcomes.camunda_process_test()

    assert [sample.id for sample in task.dataset] == ["agentic-test-specification"]
    assert "write only `/workspace/TESTING.md`" in task.dataset[0].input
