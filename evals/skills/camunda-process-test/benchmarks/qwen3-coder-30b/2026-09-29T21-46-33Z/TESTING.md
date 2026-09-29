# Test Specification for AI Agent Chat with Tools Process

## 1. High-Level Layered Strategy

### Deterministic Process Tests (Layer 1)
**Purpose**: Verify core BPMN reachability, gateway routing, and process flow logic without external dependencies.
**Isolation/External System Boundary**: Pure BPMN execution; no connectors, tools, or AI agents invoked.
**Acceptance Signal**: 100% BPMN element and sequence-flow coverage with no runtime errors.
**Execution Cadence**: Run on every commit to CI; required for merge approval.

### Segment/Point Integration Tests (Layer 2)
**Purpose**: Validate individual tool invocations within the AI agent subprocess, ensuring correct job activation and completion.
**Isolation/External System Boundary**: Connectors/tools are mocked or stubbed; no real endpoints or LLM calls.
**Acceptance Signal**: All tools can be invoked and completed successfully with expected inputs/outputs.
**Execution Cadence**: Run on every commit to CI; required for merge approval.

### Whole-Process Integration/E2E Tests (Layer 3)
**Purpose**: Validate complete user journey including tool invocation, feedback loop, and process completion.
**Isolation/External System Boundary**: Real tools invoked but with credential-free mocks or stubs; LLM behavior simulated.
**Acceptance Signal**: Complete user journey from start to finish with correct tool invocation sequence and feedback handling.
**Execution Cadence**: Run on every commit to CI; optional for merge approval, required for release.

## 2. Requirement Traceability Matrix

| Stable ID | Business Requirement | Test Layer | Named Scenario/Test | Evidence/Assertions | Dependency/Status | Comments |
|-----------|---------------------|------------|-------------------|-------------------|------------------|----------|
| PR-001 | Process must start with AI agent subprocess | Deterministic | Process Start | BPMN element visit, correct process definition | None | Required for all tests |
| PR-002 | AI agent can invoke 0-4 tools in any order | Deterministic | Tool Invocation Path | All tool paths covered, no dead ends | None | Coverage requirement |
| PR-003 | User feedback must be collected after response | Deterministic | Feedback Collection | User task element visit | None | Required for all tests |
| PR-004 | Satisfied feedback leads to process completion | Deterministic | Positive Feedback Path | End event reached, correct flow | None | Required for all tests |
| PR-005 | Rejected feedback allows follow-up input and retry | Deterministic | Negative Feedback Path | Loop back to AI agent subprocess | None | Required for all tests |
| PR-006 | Process must handle tool invocation failures gracefully | Segment | Tool Failure Handling | Boundary event fires, correct error handling | None | Required for all tests |
| PR-007 | Process must support realistic journey: first response invokes 2 tools, user rejects, second response invokes other 2 tools, user approves | E2E | Realistic Journey | All elements visited, correct tool sequence, feedback handled | None | Core business requirement |
| SIR-001 | ListUsers tool must be invocable | Segment | ListUsers Tool Test | Job activated with correct input, completed successfully | Mocked connector | Required for integration tests |
| SIR-002 | Search_Recipe tool must be invocable | Segment | Search_Recipe Tool Test | Job activated with correct input, completed successfully | Mocked connector | Required for integration tests |
| SIR-003 | Jokes_API tool must be invocable | Segment | Jokes_API Tool Test | Job activated with correct input, completed successfully | Mocked connector | Required for integration tests |
| SIR-004 | Activity_0x3prgn tool must be invocable | Segment | Activity_0x3prgn Tool Test | Job activated with correct input, completed successfully | Mocked connector | Required for integration tests |
| PIR-001 | Process must complete when user approves feedback | E2E | Completion Path | End event reached, process instance ends | None | Core business requirement |
| PIR-002 | Process must loop back when user rejects feedback | E2E | Loop Path | AI agent subprocess re-executed, correct flow | None | Core business requirement |

### Assertion Philosophy
- **Reachability**: All BPMN elements must be visited at least once
- **Routing**: Gateway branches and DMN rules must be correctly selected
- **Integration**: Tool jobs must be activated with correct inputs and completed successfully
- **Behavioral**: Process flow must match business requirements

### Out-of-Scope Items
- Real LLM model calls or API endpoints (credential-free mocks only)
- Semantic quality of AI responses
- UI behavior or user experience validation
- Production credential handling
- Performance or load testing

## 3. Numeric Targets and Machine-Gate Coverage Thresholds

| Layer | Target (%) | Machine-Gate (%) | Report Source | Current Rationale | Approval Status |
|-------|------------|------------------|---------------|-------------------|-----------------|
| Deterministic Process Tests | 100% | 100% | CPT Coverage Report | All BPMN elements and flows must be covered for process logic validation | **User-tunable** - Must be approved |
| Segment/Point Integration Tests | 100% | 100% | CPT Coverage Report | All tools must be tested individually for integration validation | **User-tunable** - Must be approved |
| Whole-Process Integration/E2E Tests | 100% | 100% | CPT Coverage Report | Complete user journey must be validated end-to-end | **User-tunable** - Must be approved |

> **Note**: These thresholds are user-tunable and must be explicitly approved before implementation. They can be adjusted based on risk assessment and business requirements.

## 4. Realistic E2E Scenarios

### Scenario 1: Successful Completion with Tool Invocation
**Inputs/Context**: User starts process, AI agent invokes ListUsers and Search_Recipe tools, user approves the response.
**Expected Outcome**: Process completes successfully with all tools invoked.
**Terminal Element**: Event_0i39jej (satisfied feedback)
**Expected Tool Set**: ListUsers, Search_Recipe
**Requirement ID**: PR-007, PIR-001
**Determinism/Retry Policy**: Deterministic, no retries needed

### Scenario 2: Feedback Loop with Tool Retry
**Inputs/Context**: User starts process, AI agent invokes Jokes_API and Activity_0x3prgn tools, user rejects the response, provides follow-up input.
**Expected Outcome**: Process loops back to AI agent subprocess, which invokes ListUsers and Search_Recipe tools.
**Terminal Element**: Event_0i39jej (satisfied feedback)
**Expected Tool Set**: ListUsers, Search_Recipe
**Requirement ID**: PR-007, PIR-002
**Determinism/Retry Policy**: Deterministic, no retries needed

### Scenario 3: Complete Feedback Loop with All Tools
**Inputs/Context**: User starts process, AI agent invokes all four tools (ListUsers, Search_Recipe, Jokes_API, Activity_0x3prgn), user rejects the response, provides follow-up input.
**Expected Outcome**: Process loops back to AI agent subprocess, which invokes the remaining two tools, user approves.
**Terminal Element**: Event_0i39jej (satisfied feedback)
**Expected Tool Set**: Jokes_API, Activity_0x3prgn
**Requirement ID**: PR-007, PIR-001, PIR-002
**Determinism/Retry Policy**: Deterministic, no retries needed

## 5. Commands and Prerequisites

### Layer 1: Deterministic Process Tests
**Command**: `mvn test -Dtest=ProcessTest`
**Prerequisites**: 
- Java 21+
- Maven (or `./mvnw`)
- Docker runtime (OrbStack, Docker Desktop, or Rancher Desktop)
- `camunda-process-test-spring` dependency in classpath

### Layer 2: Segment/Point Integration Tests
**Command**: `mvn test -Dtest=IntegrationTest`
**Prerequisites**: 
- All Layer 1 prerequisites
- Mocked connector configurations for all tools (ListUsers, Search_Recipe, Jokes_API, Activity_0x3prgn)

### Layer 3: Whole-Process Integration/E2E Tests
**Command**: `mvn test -Dtest=E2ETest`
**Prerequisites**: 
- All Layer 1 and 2 prerequisites
- Credential-free mocked endpoints for all tools
- Process test configuration with tool simulation

**Report Paths**:
- Coverage HTML Report: `target/coverage-report/report.html`
- Test Results: `target/surefire-reports/`

## 6. Artifact Links

- [Source BPMN](#) - Planned (process file not available in this environment)
- [Test Specification](./TESTING.md) - This document
- [Planned Test Artifacts](#) - Planned (test scenarios, Java classes)
- [Camunda Process Test Documentation](/workspace/skills/camunda-process-test/references/test-specification.md)
- [Fixture/Dependency Documentation](#) - Planned

## 7. Assumptions, Open Questions & Approval Gate

### Assumptions
1. The AI agent subprocess can invoke up to four tools: ListUsers, Search_Recipe, Jokes_API, Activity_0x3prgn
2. User feedback is collected via a user task with two outcomes: satisfied (approves) and rejected (provides follow-up)
3. Process loops back to the AI agent when feedback is rejected
4. All tools are implemented as service tasks with appropriate job workers

### Open Questions/Decisions
1. What specific tool configurations are required for mocking?
2. Should we include performance or load testing scenarios?
3. How should we handle error conditions in tool invocations?

### DRAFT Human Approval Gate

**DO NOT IMPLEMENT TESTS UNTIL THE FOLLOWING IS APPROVED:**

✅ Review and approve the layered strategy  
✅ Review and approve the requirement traceability matrix  
✅ Review and approve the numeric coverage targets and thresholds  
✅ Review and approve the realistic E2E scenarios  
✅ Review and approve the commands and prerequisites  

**Approval Statement**: I, the user, approve this test specification for implementation.

---
*This is a draft specification. Implementation will begin only after explicit approval.*