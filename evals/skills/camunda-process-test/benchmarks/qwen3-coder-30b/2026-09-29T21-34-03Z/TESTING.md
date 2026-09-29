# Camunda Process Test Specification

## Process Overview

**Process ID**: `ai-agent-chat-with-tools`

This process models an AI agent chat system that can invoke up to four tools:
- `ListUsers`
- `Search_Recipe` 
- `Jokes_API`
- `Activity_0x3prgn`

The process follows a user feedback loop where the user can either approve or reject responses, causing the agent to loop back and potentially invoke different tools.

## 1. Three-Layer Strategy

### Deterministic Process Tests
**Purpose**: Verify BPMN reachability, gateway routing, and basic process flow without external dependencies.
**Isolation/External System Boundary**: Offline, credential-free, deterministic execution.
**Acceptance Signal**: 100% BPMN element and sequence-flow coverage.
**Execution Cadence**: Run on every commit to CI.

### Segment/Point Integration Tests
**Purpose**: Validate tool invocations and connector behavior in isolation.
**Isolation/External System Boundary**: Mocked or local endpoints for tools.
**Acceptance Signal**: All tool invocations are correctly triggered with expected parameters.
**Execution Cadence**: Run on every commit to CI, plus manual verification of live endpoints.

### Whole-Process Integration/E2E Tests
**Purpose**: Validate complete user journey from start to finish with realistic scenarios.
**Isolation/External System Boundary**: Live endpoints or mocked services.
**Acceptance Signal**: End-to-end journeys complete successfully with correct tool usage.
**Execution Cadence**: Run on every commit to CI, plus manual verification of live endpoints.

## 2. Requirement Traceability Matrix

| Stable ID | Business Requirement | Test Layer | Named Scenario/Test | Evidence/Assertions | Dependency/Status | Comments |
|-----------|---------------------|------------|-------------------|-------------------|------------------|----------|
| PR-001 | AI agent can invoke zero tools | Deterministic Process | `ai-agent-no-tools` | Agent completes without invoking any tools | N/A | Basic process flow |
| PR-002 | AI agent can invoke one tool | Deterministic Process | `ai-agent-one-tool` | Agent invokes exactly one tool and completes | N/A | Single tool invocation |
| PR-003 | AI agent can invoke two tools | Deterministic Process | `ai-agent-two-tools` | Agent invokes exactly two tools and completes | N/A | Two tool invocation |
| PR-004 | AI agent can invoke three tools | Deterministic Process | `ai-agent-three-tools` | Agent invokes exactly three tools and completes | N/A | Three tool invocation |
| PR-005 | AI agent can invoke four tools | Deterministic Process | `ai-agent-four-tools` | Agent invokes exactly four tools and completes | N/A | Four tool invocation |
| PR-006 | User feedback loop allows rejection | Deterministic Process | `user-feedback-rejection` | User feedback task is reached, rejection path loops back | N/A | Feedback rejection handling |
| PR-007 | User feedback loop allows approval | Deterministic Process | `user-feedback-approval` | User feedback task is reached, approval path completes | N/A | Feedback approval handling |
| SIR-001 | First response invokes two tools, user rejects with follow-up input | E2E Integration | `first-response-two-tools-reject` | Agent invokes two tools, user rejects, agent loops back and invokes other two tools, user approves | Live endpoints optional | Core business journey |
| SIR-002 | First response invokes all four tools, user approves | E2E Integration | `first-response-four-tools-approve` | Agent invokes all four tools, user approves | Live endpoints optional | Full tool invocation |
| SIR-003 | First response invokes no tools, user approves | E2E Integration | `first-response-no-tools-approve` | Agent completes without tools, user approves | Live endpoints optional | Minimal flow |

### Assertion Philosophy
- **Reachability**: All elements must be visited at least once.
- **Routing**: Gateway branches and end events must be selected correctly.
- **Tool Contracts**: Tool invocations must match expected parameters (shape, status class, required fields).
- **No Volatility**: Assertions should not depend on exact payloads or generated response wording.

### Out-of-Scope Items
- Semantic quality of AI responses
- Real LLM calls in required CI path
- Authenticated production dependencies
- UI behavior testing

## 3. Coverage Thresholds

| Layer | Target % | Machine-Gate % | Report Source | Current Rationale | Approval |
|-------|----------|----------------|---------------|-------------------|----------|
| Deterministic Process | 100% | 100% | CPT coverage report | All BPMN elements and sequence flows must be covered | **User-tunable** - Must be approved |
| Segment Integration | 100% | 100% | CPT coverage report | All tool invocations must be tested in isolation | **User-tunable** - Must be approved |
| E2E Integration | 95% | 90% | CPT coverage report + manual verification | Realistic journeys with live endpoints | **User-tunable** - Must be approved |

> **Note**: Thresholds are user-tunable and must be explicitly approved before implementation begins.

## 4. Realistic E2E Scenarios

### Scenario 1: First Response Two Tools, Rejection, Second Response Two Tools
- **Inputs/Context**: User asks for recipe suggestions
- **Expected Outcome**: AI agent invokes `ListUsers` and `Search_Recipe`, user rejects with follow-up input
- **Terminal Element**: `Event_0i39jej` (Satisfied)
- **Expected Tool Set**: First response: `ListUsers`, `Search_Recipe`; Second response: `Jokes_API`, `Activity_0x3prgn`
- **Requirement ID**: SIR-001
- **Determinism/Retry Policy**: Deterministic, retry on failure

### Scenario 2: First Response All Four Tools, Approval
- **Inputs/Context**: User asks for comprehensive information
- **Expected Outcome**: AI agent invokes all four tools (`ListUsers`, `Search_Recipe`, `Jokes_API`, `Activity_0x3prgn`), user approves
- **Terminal Element**: `Event_0i39jej` (Satisfied)
- **Expected Tool Set**: All four tools invoked in any order
- **Requirement ID**: SIR-002
- **Determinism/Retry Policy**: Deterministic, retry on failure

### Scenario 3: First Response No Tools, Approval
- **Inputs/Context**: User asks for simple information that doesn't require tool invocation
- **Expected Outcome**: AI agent completes without invoking any tools, user approves
- **Terminal Element**: `Event_0i39jej` (Satisfied)
- **Expected Tool Set**: No tools invoked
- **Requirement ID**: SIR-003
- **Determinism/Retry Policy**: Deterministic, retry on failure

## 5. Commands and Prerequisites

### Running Deterministic Process Tests
```bash
cd /workspace
mvn test -Dtest=ProcessTest
```

### Running Segment Integration Tests  
```bash
cd /workspace
mvn test -Dtest=SegmentIntegrationTest
```

### Running E2E Integration Tests
```bash
cd /workspace
mvn test -Dtest=E2EIntegrationTest
```

**Prerequisites**:
- Java 21+
- Maven (or `./mvnw`)
- Docker runtime (OrbStack, Docker Desktop, or Rancher Desktop)
- Process under test must be lint clean (`c8ctl bpmn lint`)

**Report Paths**:
- Coverage HTML: `/workspace/target/coverage-report/report.html`
- Test results: `/workspace/target/surefire-reports/`

## 6. Artifact Links

- **BPMN Source**: [`/workspace/fixture/ai-agent-chat-with-tools.bpmn`](file:///workspace/fixture/ai-agent-chat-with-tools.bpmn)
- **Test Specification**: This document (`/workspace/TESTING.md`)
- **Planned Test Artifacts**:
  - `/workspace/src/test/java/io/camunda/tests/ProcessTest.java` (planned)
  - `/workspace/src/test/resources/scenarios/` (planned)
- **CPT Documentation**: [Camunda Process Test Documentation](file:///workspace/skills/camunda-process-test/references/test-specification.md)
- **Fixture/Dependency Documentation**: [Three-Layer Strategy](file:///workspace/skills/camunda-process-test/references/three-layer-strategy.md)

## 7. Assumptions, Open Questions & Approval Gate

### Assumptions
1. The AI agent can dynamically decide which tools to invoke based on user input
2. All tools are available and properly configured in the test environment
3. The process is executable and lint clean
4. The feedback loop works correctly with both approval and rejection paths

### Open Questions/Decisions
1. Should we implement a specific tool invocation order or allow any order?
2. How should we handle tool failures during E2E tests?
3. What level of mocking is required for the tools in integration tests?

### DRAFT Approval Gate

**DO NOT IMPLEMENT TESTS UNTIL THE FOLLOWING IS APPROVED:**

✅ All requirements and scenarios reviewed and accepted  
✅ Coverage thresholds approved  
✅ Dependencies and prerequisites confirmed  
✅ Tool invocation behavior defined  

This specification is a draft and requires explicit human approval before any test implementation begins.