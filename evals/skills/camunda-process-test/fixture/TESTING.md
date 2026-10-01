# Testing and acceptance criteria

**Status: APPROVED for the canonical outcome-eval implementation.**

## High-level testing strategy

| Layer | Purpose | External boundary | Acceptance signal | Run cadence |
| --- | --- | --- | --- | --- |
| Deterministic process | Prove BPMN reachability and routing | Controlled agent and tool jobs; no network | 100% reachable elements and sequence flows | Every CI run |
| Point integration | Prove each tool contract independently | Local or mocked dependencies | 100% of four tool paths | Every CI run |
| Process integration/E2E | Prove named business outcomes | Local or mocked dependencies | Required journeys complete | Every CI run |

Optional live-dev runs may exercise configured endpoints, but are not part of
the required gate.

## Requirements and traceability

| ID | Requirement | Layer | Scenario | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| PR-1 | A response can complete without tools | Deterministic | Direct response — no tool | No tool activates; feedback is reached | Approved |
| PR-2 | Each of four tools is reachable | Deterministic | Agent response — all tools | Each tool completes | Approved |
| PR-3 | Satisfied feedback completes | Deterministic | Feedback — approved | Final event and process complete | Approved |
| PR-4 | Rejected feedback retries | Deterministic | Feedback — retry | Agent host activates twice | Approved |
| SIR-1 | ListUsers contract works alone | Point integration | ListUsers — stable contract | Only ListUsers completes | Approved |
| SIR-2 | Search_Recipe contract works alone | Point integration | Search_Recipe — stable contract | Only Search_Recipe completes | Approved |
| SIR-3 | Jokes_API contract works alone | Point integration | Jokes_API — stable contract | Only Jokes_API completes | Approved |
| SIR-4 | Activity_0x3prgn works alone | Point integration | Activity tool — stable contract | Only Activity_0x3prgn completes | Approved |
| PIR-1 | A rejected answer can be refined and approved | E2E | Feedback journey — retry then approve | All tools reached; process completes | Approved |

Assertions cover reachability, routing, stable contract shape, and named
business outcomes. Exact model prose, semantic response quality, production
credentials, and UI behavior are out of scope.

## Coverage thresholds

| Layer | Target | Machine gate | Report |
| --- | --- | --- | --- |
| Deterministic process | 100% | 100% reachable elements and flows | HTML and JSON coverage |
| Point integration | 100% | 4/4 tool paths | JSON summary |
| Process integration/E2E | 100% required outcomes | Retry-then-approve passes | HTML and JSON coverage |

These thresholds are user-tunable. This fixture records their explicit approval
for the canonical eval; changes require renewed approval.

## Realistic E2E scenarios

1. **Useful first response** — invoke two suitable tools, approve the answer,
   and complete at `Event_0i39jej`.
2. **Refined response** — invoke two tools, reject with follow-up context,
   invoke the other two tools in any order, approve, and complete at
   `Event_0i39jej`.
3. **Direct response** — answer without tools, approve, and complete at
   `Event_0i39jej`.

## Running the tests

Prerequisites are Java 21+, Maven, and the local Camunda test runtime.

- Deterministic: `mvn test -Dtest=ProcessTest`
- Point integration: `mvn test -Dtest=PointIntegrationTest`
- E2E: `mvn test -Dtest=ProcessIntegrationTest`
- Required complete gate: `mvn test`

Publish the machine summary and `target/coverage-report/report.html`.

## Artifacts and links

- [Source BPMN](./ai-agent-chat-with-tools.bpmn)
- [Approved specification](./TESTING.md)
- [Planned test sources](../test/)
- [Camunda Process Test documentation](https://docs.camunda.io/docs/apis-tools/testing/)
