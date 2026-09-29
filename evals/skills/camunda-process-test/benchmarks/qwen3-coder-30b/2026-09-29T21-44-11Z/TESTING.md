# Test Specification for `ai-agent-chat-with-tools` Process

## 1. High-Level Layered Strategy

### Deterministic Process Tests (Layer 1)
**Purpose**: Verify BPMN reachability, gateway routing, boundary event firing, and end-event selection without external dependencies.
**Isolation/External System Boundary**: Offline, credential-free, deterministic execution using mocked or stubbed tool responses.
**Acceptance Signal**: 100% BPMN element and sequence-flow coverage with no runtime failures.
**Execution Cadence**: Run on every commit to CI; required for merge approval.

### Segment/Point Integration Tests (Layer 2)
**Purpose**: Validate integration points between the AI agent subprocess and its tools, ensuring correct tool invocation and response handling.
**Isolation/External System Boundary**: Tools are mocked or stubbed; no live endpoints or model runs in CI.
**Acceptance Signal**: All tool invocations within the ad-hoc subprocess are correctly triggered and handled.
**Execution Cadence**: Run on every commit to CI; required for merge approval.

### Whole-Process Integration/E2E Tests (Layer 3)
**Purpose**: Validate end-to-end user journey through the process, including feedback loops and tool invocation patterns.
**Isolation/External System Boundary**: Live endpoints or model runs are optional and documented separately; CI must be credential-free.
**Acceptance Signal**: Realistic user journeys complete successfully with expected tool usage patterns.
**Execution Cadence**: Run on every commit to CI (minimal set); full E2E tests run nightly or on demand.

## 2. Requirement Traceability Matrix

| Stable ID | Business Requirement | Test Layer | Named Scenario/Test | Evidence/Assertions | Dependency/Status | Comments |
|-----------|---------------------|------------|-------------------|-------------------|------------------|----------|
| PR-001 | AI agent subprocess can invoke zero to four tools in response to user input | Process | `ai-agent-no-tool-invocation` | Verify ad-hoc subprocess completes without tool calls | None | Deterministic process test |
| PR-002 | AI agent subprocess invokes `ListUsers` tool when appropriate | Process | `ai-agent-list-users-tool` | Verify `ListUsers` job is activated and completed | None | Deterministic process test |
| PR-003 | AI agent subprocess invokes `Search_Recipe` tool when appropriate | Process | `ai-agent-search-recipe-tool` | Verify `Search_Recipe` job is activated and completed | None | Deterministic process test |
| PR-004 | AI agent subprocess invokes `Jokes_API` tool when appropriate | Process | `ai-agent-jokes-api-tool` | Verify `Jokes_API` job is activated and completed | None | Deterministic process test |
| PR-005 | AI agent subprocess invokes `Activity_0x3prgn` tool when appropriate | Process | `ai-agent-activity-tool` | Verify `Activity_0x3prgn` job is activated and completed | None | Deterministic process test |
| PR-006 | User feedback loop allows for rejection and follow-up input | Process | `user-feedback-rejection-loop` | Verify feedback rejection leads to new agent invocation | None | Deterministic process test |
| PR-007 | Process completes when user approves feedback | Process | `user-feedback-approval-completion` | Verify approval reaches final event | None | Deterministic process test |
| SIR-001 | First response invokes two tools, user rejects with follow-up input | E2E | `first-response-two-tools-rejection-followup` | Verify first agent invocation uses 2 tools, rejection triggers new invocation | None | E2E test |
| SIR-002 | Second response invokes the other two tools, user approves and process completes | E2E | `second-response-other-tools-approval-completion` | Verify second agent invocation uses 2 different tools, approval completes process | None | E2E test |
| PIR-001 | Process handles tool failures gracefully | Integration | `tool-failure-handling` | Verify error boundary events fire correctly on tool failure | None | Integration test |
| PIR-002 | Process handles user feedback rejection properly | Integration | `user-feedback-rejection-handling` | Verify rejection path correctly loops back to agent subprocess | None | Integration test |

### Assertion Philosophy
Assertions focus on:
1. **Reachability**: Every BPMN element is visited at least once
2. **Routing**: Correct gateway branches and boundary event firing
3. **Integration**: Tool invocation patterns match expected usage
4. **Completion**: End events are reached with correct conditions

Out-of-scope items:
- Semantic quality of AI responses
- Exact wording or formatting of tool outputs
- Real LLM calls in CI path
- Authenticated production dependencies
- UI behavior validation

## 3. Coverage Thresholds

### Layer 1 (Deterministic Process Tests)
- **Target**: 100% BPMN element and sequence-flow coverage
- **Machine-Gate**: 100% coverage with no runtime failures
- **Report Source**: CPT HTML coverage report (`target/coverage-report/report.html`)
- **Current Rationale**: Process correctness must be verified without external dependencies
- **User-Tunable**: Yes, but must be approved by stakeholders

### Layer 2 (Segment/Point Integration Tests)
- **Target**: 100% tool invocation patterns covered
- **Machine-Gate**: All expected tools are invoked in correct contexts
- **Report Source**: CPT test execution logs and coverage data
- **Current Rationale**: Tool integration must be validated without live endpoints
- **User-Tunable**: Yes, but must be approved by stakeholders

### Layer 3 (Whole-Process Integration/E2E Tests)
- **Target**: 100% realistic user journeys covered
- **Machine-Gate**: All E2E scenarios complete successfully with expected tool usage
- **Report Source**: CPT test execution logs and coverage data
- **Current Rationale**: End-to-end behavior must be validated for business value
- **User-Tunable**: Yes, but must be approved by stakeholders

## 4. Realistic E2E Scenarios

### Scenario 1: First Response with Two Tools, Rejection, Second Response with Other Two Tools
**Inputs/Context**: User provides initial input that triggers AI agent to invoke `ListUsers` and `Search_Recipe` tools; user rejects the response with follow-up input.
**Expected Outcome**: Agent subprocess completes with two tool invocations, feedback rejection loops back to new agent invocation.
**Terminal Element**: `Activity_0x3prgn` (second agent invocation)
**Expected Tool Set**: `ListUsers`, `Search_Recipe` in first invocation; `Jokes_API`, `Activity_0x3prgn` in second
**Requirement ID**: SIR-001
**Determinism/Retry Policy**: Deterministic, retry on failure

### Scenario 2: Second Response with Other Two Tools, User Approval
**Inputs/Context**: After rejection and follow-up input, agent subprocess invokes `Jokes_API` and `Activity_0x3prgn` tools; user approves the response.
**Expected Outcome**: Agent subprocess completes with two tool invocations, feedback approval leads to process completion.
**Terminal Element**: `Event_0i39jej` (process completion)
**Expected Tool Set**: `Jokes_API`, `Activity_0x3prgn` in second invocation
**Requirement ID**: SIR-002
**Determinism/Retry Policy**: Deterministic, retry on failure

### Scenario 3: Direct Completion Without Tool Invocation
**Inputs/Context**: User provides input that triggers AI agent to complete without invoking any tools.
**Expected Outcome**: Agent subprocess completes directly, feedback approval leads to process completion.
**Terminal Element**: `Event_0i39jej` (process completion)
**Expected Tool Set**: None
**Requirement ID**: PR-001
**Determinism/Retry Policy**: Deterministic, retry on failure

## 5. Commands and Prerequisites

### Layer 1: Deterministic Process Tests
**Command**: `mvn test -Dtest=ProcessTest`
**Prerequisites**: Java 21+, Maven, Docker runtime
**Report Path**: `target/coverage-report/report.html`

### Layer 2: Segment/Point Integration Tests
**Command**: `mvn test -Dtest=IntegrationTest`
**Prerequisites**: Java 21+, Maven, Docker runtime
**Report Path**: `target/test-reports/integration-test.html`

### Layer 3: Whole-Process Integration/E2E Tests
**Command**: `mvn test -Dtest=E2ETest`
**Prerequisites**: Java 21+, Maven, Docker runtime
**Report Path**: `target/test-reports/e2e-test.html`

## 6. Artifact Links

- **Source BPMN**: `/workspace/fixture/ai-agent-chat-with-tools.bpmn` (planned)
- **Test Specification**: `/workspace/TESTING.md`
- **Planned Test Artifacts**: 
  - `src/test/resources/scenarios/process.test.json` (planned)
  - `src/test/resources/scenarios/integration.test.json` (planned)
  - `src/test/resources/scenarios/e2e.test.json` (planned)
- **CPT Documentation**: [Camunda Process Test Documentation](https://github.com/camunda/skills/tree/main/camunda-process-test/references)
- **Fixture/Dependency Documentation**: `/workspace/fixture/README.md` (planned)

## 7. Assumptions, Open Questions, and Approval Gate

### Assumptions
1. The process uses Camunda 8.9+ with the AI Agent Sub-process connector
2. Tool invocations are modeled as service tasks within the ad-hoc subprocess
3. Feedback loop is implemented using a user task with conditional sequence flows
4. Process can be deployed and tested in an embedded Zeebe engine

### Open Questions/Decisions
1. Should we include specific tool response mocking strategies?
2. How should we handle time-based boundary events if any exist?
3. What are the exact tool names and their expected inputs/outputs?

### DRAFT Human Approval Gate
**DO NOT IMPLEMENT TESTS UNTIL THE FOLLOWING IS APPROVED:**

✅ Business requirements and test layers are clearly defined  
✅ Requirement traceability matrix is complete and accurate  
✅ Coverage thresholds are reasonable and approved  
✅ E2E scenarios are realistic and cover key user journeys  
✅ Commands and prerequisites are correct  
✅ Artifact links are properly specified  

**Approval**: [ ] Not yet approved - Tests will not be implemented until this specification is reviewed and approved by stakeholders.
