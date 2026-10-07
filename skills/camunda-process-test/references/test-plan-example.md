# AI Agent Chat With Tools test plan

> **Illustrative proposal:** This repository does not contain the solution fixture
> or test runner shown below. The artifact paths, Maven command, and report
> locations are examples, not verified or passing evidence. Replace them with
> the target project's actual files and confirm how each suite is run before
> adopting this plan.

The four test layers answer progressively broader questions: does the process route correctly, does each integration work in isolation, does the complete process reach its business outcome, and does a person observe the expected external behavior?

## Process tests

- **Verifies:** Every reachable BPMN element and sequence flow, including no-tool, each tool, rejection, retry, and approval.
- **Required evidence:** 10/10 reachable elements and 6/6 sequence flows in the CPT coverage report.
- **Mocks:** All external systems.

| ID | Test | Guarantee |
|---|---|---|
| P-1 | `process/no-tool` | A direct answer can complete without a tool. |
| P-2 | `process/feedback-retry` | Rejected feedback retries and later approval completes. |
| P-3 | `process/all-tools` | All four tools are reachable through the agent subprocess. |

## Point integration tests

- **Verifies:** Controlled agent outcomes select each intended tool behavior, and every connector path independently returns its documented stable shape.
- **Required evidence:** All 5 controlled agent scenarios complete the expected agent or tool element, and all 4 local connector-contract tests pass.
- **Mocks:** The model is replaced with controlled outcomes; connector dependencies use local stubs.

| ID | Test | Guarantee |
|---|---|---|
| S-1 | `point-integration/agent-no-tool` | A controlled direct-answer outcome completes without activating a tool. |
| S-2 | `point-integration/agent-list-users` | A controlled user-directory outcome activates only the user-directory tool. |
| S-3 | `point-integration/agent-search-recipe` | A controlled recipe outcome activates only the recipe-search tool. |
| S-4 | `point-integration/agent-jokes-api` | A controlled joke outcome activates only the jokes tool. |
| S-5 | `point-integration/agent-technology-products` | A controlled product outcome activates only the technology-products tool. |
| S-6 | `point-integration/connector-list-users` | The user-directory connector returns the documented user shape from a local stub. |
| S-7 | `point-integration/connector-search-recipe` | The recipe-search connector returns the documented recipe shape from a local stub. |
| S-8 | `point-integration/connector-jokes-api` | The jokes connector returns non-empty text from a local stub. |
| S-9 | `point-integration/connector-technology-products` | The technology-products connector returns the documented product shape from a local stub. |

## Process integration tests

- **Verifies:** Controlled agent outcomes select the expected tool set, local connector stubs return usable results, and the complete process reaches the expected outcome.
- **Required evidence:** 3/3 automated scenarios pass.
- **Mocks:** Controlled agent outcomes and local connector stubs.
- **Boundary:** These tests verify process behavior, not model reliability or external-system impacts.

| ID | Test | Guarantee |
|---|---|---|
| PI-1 | `process-integration/users-and-products` | A users-and-products request completes the user-directory and technology-products tools, then completes. |
| PI-2 | `process-integration/joke-and-recipe` | A joke-and-recipe request completes the jokes and recipe-search tools, then completes. |
| PI-3 | `process-integration/feedback-retry` | The first turn completes jokes and recipe search; rejected feedback triggers a second turn completing user directory and technology products; later approval completes. |

Tool sets are unordered. Tests assert expected tool completion, result-variable existence, feedback topology, and terminal state, but not exact generated wording.

**Limitation:** Test Studio only displays editable summaries for singular element assertions and basic variable assertions. The importable scenarios therefore prove that expected tools complete and result variables exist, but do not automatically reject additional tool activation or validate result shape with FEEL. The managed point-integration tests retain shape and isolation assertions; optional live tests verify model selection and human-facing behavior.

**Assertion strategy:** This plan prioritizes business visibility for importable live scenarios, accepting weaker Test Studio assertions such as checking that `toolCallResult` exists. Managed CPT tests retain stronger native assertions such as FEEL result-shape expressions. Do not silently weaken an assertion: choose and document whether a suite optimizes for CPT power or Test Studio visibility.

## Manual tests

- **Verifies:** A person can complete the expected journeys and observe the expected behavior in the process and external systems.
- **Required evidence:** Optional live-development checks; require them only when project policy says so.
- **Mocks:** None.

| ID | Test | Steps and pass condition |
|---|---|---|
| M-1 | Users and products | Ask for the available users and sample technology products. Confirm both external services return usable information, the response includes both categories, and approval completes the process. |
| M-2 | Joke and recipe | Ask for a safe joke and a pasta recipe. Confirm both external services return usable information, the response includes both results, and approval completes the process. |
| M-3 | Feedback retry | Ask for a joke and recipe, reject the response, then ask for users and technology products. Confirm both turns use the appropriate external services and approval completes the process after two feedback steps. |

Do not judge exact wording or tool order. Repeating these checks to measure model reliability is optional.

## Run and inspect

Proposed automated prerequisites: Java 21+, Maven, a Docker-compatible runtime, controlled agent fixtures, and local connector stubs. Required offline runs should need no network, credentials, SaaS cluster, or LLM budget.

Proposed command for a target project that implements and loads these required offline suites in Maven (not run or verified by this skills repository):

```bash
cd solutions/ai-agent-chat-with-tools/test
mvn test
```

The target project's default Maven lifecycle should run every required offline automated gate. Verify that its POM loads each suite before treating this command as a gate. Run optional live-development checks separately.

Optional live development: with an eligible Camunda SaaS cluster, LLM budget, and access to the public services, run the Test Studio scenarios under an explicit live profile. These runs assess model/tool-selection behavior and external connectivity; they do not replace the required offline gates.

Reports:

- Interactive coverage: `test/target/coverage-report/report.html`
- Machine coverage: `test/target/coverage-report/report.json`
- JUnit results: `test/target/surefire-reports/`
- Automated offline process-integration results: `test/target/surefire-reports/` (if the target project wires these suites into Maven)
- Optional live Test Studio runs: Test Studio run history
- Manual acceptance: policy checklist, only when project policy requires it

## Artifacts

- Source BPMN: `./ai-agent-chat-with-tools.bpmn`
- Deterministic CPT scenarios: `./test/src/test/resources/test-cases/ai-agent-chat-with-tools.test.json`
- Managed point-integration tests: `./test/src/test/java/io/camunda/tests/LiveConnectorIntegrationTest.java`
- Live point-integration Test Studio scenarios: `./ai-agent-chat-with-tools.integration.test.json`
- Automated process-integration scenarios: `./ai-agent-chat-with-tools.test.json`
- Solution prerequisites and test details: `./README.md`
- [Camunda Process Test documentation](https://docs.camunda.io/docs/apis-tools/testing/getting-started/)
