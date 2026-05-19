# Authoring CPT scenarios

> Default to `.test.json` (instruction-based). Use Java `@Test` only when JSON cannot express the test — see [§ Java fallback](#java-fallback) at the bottom.

## `.test.json` format

Instruction-based CPT format (8.9+). Each `.test.json` file is loaded by `@TestCaseSource` and run as one parameterized JUnit test per `testCases[]` entry.

## File skeleton

```json
{
  "$schema": "https://camunda.com/json-schema/cpt-test-cases/8.9/schema.json",
  "testCases": [
    {
      "name": "<who/what> — <outcome>",
      "description": "One sentence in business language.",
      "instructions": [
        /* … */
      ]
    }
  ]
}
```

Place at `src/test/resources/scenarios/<processId>.test.json`. One file per process; many `testCases[]` per file.

## Naming

- `name`: `<who/what> — <outcome>`. Examples: `"manager approves — finance also approves"`, `"notification fails — error boundary fires"`. Avoid: `test1`, `happy`, `gateway A`.
- `description`: one sentence in business language. No element IDs.

## Instructions reference

### `CREATE_PROCESS_INSTANCE`

Always the first instruction.

```json
{
  "type": "CREATE_PROCESS_INSTANCE",
  "processDefinitionSelector": { "processDefinitionId": "expense-approval" },
  "variables": { "amount": 200, "department": "Engineering" }
}
```

Input variables here drive every downstream gateway and DMN decision. Pick values that route to the segment under test.

### `COMPLETE_JOB`

Completes a service-task job. Used for any `<bpmn:serviceTask>` without `<zeebe:userTask/>`.

```json
{
  "type": "COMPLETE_JOB",
  "jobSelector": { "elementId": "Task_SendNotification" },
  "variables": {}
}
```

`variables` is the output payload the mocked worker would produce. Leave empty unless a downstream gateway or DMN consumes a value the job sets.

### `COMPLETE_USER_TASK`

Completes a Camunda user task (`<zeebe:userTask/>`).

```json
{
  "type": "COMPLETE_USER_TASK",
  "userTaskSelector": { "elementId": "Task_ManagerReview" },
  "variables": { "managerDecision": "Approve" }
}
```

The variable map matches the linked form's component `key` values. Only include keys downstream logic reads.

### `THROW_BPMN_ERROR_FROM_JOB`

Triggers a BPMN error boundary on a service task.

```json
{
  "type": "THROW_BPMN_ERROR_FROM_JOB",
  "jobSelector": { "elementId": "Task_SendNotification" },
  "errorCode": "NOTIFICATION_FAILED"
}
```

`errorCode` must match the `errorCode` on the `<bpmn:error>` referenced by the boundary event exactly. Mismatch → process continues to the happy path, assertion fails.

Optional fields: `errorMessage` (surfaced on the incident), `variables` (set on completion).

### `COMPLETE_JOB_AD_HOC_SUB_PROCESS`

Completes the worker job for an ad-hoc sub-process that runs in **job-worker mode** (has a `<zeebe:taskDefinition type="…">`, e.g. the AI Agent Sub-process connector). The job's result picks which inner activities to launch next or marks the AHSP completion condition fulfilled.

```json
{
  "type": "COMPLETE_JOB_AD_HOC_SUB_PROCESS",
  "jobSelector": { "elementId": "AhsAgent" },
  "activateElements": [
    { "elementId": "Tool_FetchOrder", "variables": { "orderId": "ORD-1" } }
  ]
}
```

Optional fields:

- `variables` — variables set on the outer AHSP scope when the job completes.
- `activateElements` — list of inner activities to start; each carries `elementId` and optional `variables`. Order matches the order specified.
- `completionConditionFulfilled` (boolean, default `false`) — set `true` once the agent decides it is done; the AHSP terminates after the activated elements finish.
- `cancelRemainingInstances` (boolean, default `false`) — set `true` to cancel still-running inner activities when the AHSP completes.

A plain `COMPLETE_JOB` against the AHSP outer job will hang — the worker contract is `complete-with-result`, not `complete-with-variables`. The internal-mode vs. job-worker-mode distinction is covered in **camunda-bpmn**; the Java equivalent (`context.completeJobOfAdHocSubProcess`) is in [test-context.md § Ad-hoc sub-process completion](test-context.md#ad-hoc-sub-process-completion-89).

For ad-hoc *internal* mode (no `<zeebe:taskDefinition>`, declarative `activeElementsCollection` / `completionCondition`), there is no outer job — drive routing through the AHSP's input variables on `CREATE_PROCESS_INSTANCE` and complete each inner activity directly.

### `ASSERT_ELEMENT_INSTANCES`

Asserts an element was reached.

```json
{
  "type": "ASSERT_ELEMENT_INSTANCES",
  "processInstanceSelector": { "processDefinitionId": "expense-approval" },
  "elementSelectors": [{ "elementId": "Task_ManagerReview" }],
  "state": "IS_ACTIVE"
}
```

States: `IS_ACTIVE`, `IS_COMPLETED`, `IS_TERMINATED`. Use `IS_ACTIVE` for elements the segment must visit before a manual `COMPLETE_*`. Use `IS_COMPLETED` for end events.

### `ASSERT_PROCESS_INSTANCE`

Asserts overall process state. Use only when the segment runs to an end event.

```json
{
  "type": "ASSERT_PROCESS_INSTANCE",
  "processInstanceSelector": { "processDefinitionId": "expense-approval" },
  "state": "IS_COMPLETED"
}
```

### Instructions for DMN

The instructions above test the *process*; these test the *decision*. A BPMN-completes test passes even if every DMN output is wrong — assert the decision directly when its rules matter. See **camunda-dmn** § testing-decisions for what to assert per hit policy.

The three DMN instructions below are part of the 8.9 `.test.json` grammar. The equivalent Java API (`assertThatDecision`, `DecisionSelectors`, `mockDmnDecision`) shipped with CPT itself and is available on 8.8+.

#### `EVALUATE_DECISION`

Runs a DMN decision without a process instance. The leaf of a chained DRG (`B requires A`) auto-evaluates upstream decisions, so one call exercises the whole graph.

```json
{
  "type": "EVALUATE_DECISION",
  "decisionDefinitionSelector": { "decisionDefinitionId": "dish" },
  "variables": { "season": "Winter" }
}
```

#### `ASSERT_DECISION`

Asserts which rules fired and what the decision output. Fields: `output`, `matchedRules: [int]` (1-based ordinals in rule order, **not** BPMN ids), `notMatchedRules: [int]`, `noMatchedRules: boolean`.

```json
{
  "type": "ASSERT_DECISION",
  "decisionSelector": { "decisionDefinitionId": "dish" },
  "output": ["Tortellini", "Roastbeef"],
  "matchedRules": [1, 2]
}
```

For UNIQUE/ANY/FIRST: single ordinal. For RULE ORDER/COLLECT: all matched ordinals as a list. For "no rule should match": `"noMatchedRules": true`.

Pair with `EVALUATE_DECISION` for standalone decision tests, or place after the process scenario completes to assert what fired in-process.

#### `MOCK_DMN_DECISION`

Replaces a real DMN evaluation with a fixed output. Use to isolate BPMN-flow tests from DMN logic — BPMN scenarios stay stable when a rule changes.

```json
{
  "type": "MOCK_DMN_DECISION",
  "decisionDefinitionId": "dish",
  "output": ["Tortellini"]
}
```

Mocking and asserting are complementary, not interchangeable: mock the DMN in BPMN-flow tests; assert the DMN directly in decision-focused tests.

### `MOCK_JOB_WORKER_COMPLETE_JOB`

Standing stub: every job of `jobType` is auto-completed with the same `variables`. Cleaner than repeating `COMPLETE_JOB` per iteration in multi-instance loops or polling worker tests.

```json
{ "type": "MOCK_JOB_WORKER_COMPLETE_JOB", "jobType": "fetch-rate", "variables": { "rate": 0.05 } }
```

Optional `useExampleData` (boolean) — use the BPMN element's `example` data property instead of `variables`.

### `MOCK_JOB_WORKER_THROW_BPMN_ERROR`

Standing stub: every job of `jobType` throws a BPMN error. Optional `errorMessage`, `variables`.

```json
{ "type": "MOCK_JOB_WORKER_THROW_BPMN_ERROR", "jobType": "send-email", "errorCode": "EMAIL_FAILED" }
```

### `MOCK_CHILD_PROCESS`

Replaces a called process with a no-op that completes immediately. Optional `variables` for the mocked output.

```json
{ "type": "MOCK_CHILD_PROCESS", "processDefinitionId": "payment-process", "variables": { "paid": true } }
```

### `COMPLETE_JOB_USER_TASK_LISTENER`

Completes a user-task listener job (`creating`/`assigning`/`updating`/`completing`/`canceling`). Optional `denied` (boolean), `deniedReason`, `corrections` (`assignee`, `dueDate`, `followUpDate`, `priority`, `candidateGroups`, `candidateUsers`).

```json
{
  "type": "COMPLETE_JOB_USER_TASK_LISTENER",
  "jobSelector": { "elementId": "Approve" },
  "corrections": { "assignee": "manager-1" }
}
```

### `EVALUATE_CONDITIONAL_START_EVENT`

Triggers conditional start events against the given variables.

```json
{ "type": "EVALUATE_CONDITIONAL_START_EVENT", "variables": { "stock": 0 } }
```

### `PUBLISH_MESSAGE`

Buffers a message — correlates lazily when a matching subscription appears.

```json
{ "type": "PUBLISH_MESSAGE", "name": "order-paid", "correlationKey": "ORD-1", "variables": {} }
```

Optional `timeToLive` (ms), `messageId` (de-duplication).

### `CORRELATE_MESSAGE`

Correlates a message immediately — fails if no subscription is waiting. Use when the test must assert the subscription is open before the message lands.

```json
{ "type": "CORRELATE_MESSAGE", "name": "order-paid", "correlationKey": "ORD-1" }
```

### `BROADCAST_SIGNAL`

```json
{ "type": "BROADCAST_SIGNAL", "signalName": "shutdown", "variables": {} }
```

### `INCREASE_TIME` / `SET_TIME`

```json
{ "type": "INCREASE_TIME", "duration": "PT25H" }
{ "type": "SET_TIME", "time": "2026-05-19T00:00:00Z" }
```

`duration` is ISO 8601 (`PT…H/M/S`, `P…D`). `time` is ISO 8601 instant.

### `UPDATE_VARIABLES`

Creates or updates variables on a process instance or element scope mid-test. Optional `elementSelector` for element-local scope. Use sparingly — driving routing via real instructions is closer to production.

```json
{
  "type": "UPDATE_VARIABLES",
  "processInstanceSelector": { "processDefinitionId": "expense-approval" },
  "variables": { "amount": 1500 }
}
```

### `RESOLVE_INCIDENT`

Resolves a matching incident; if the incident is on a job, retries are increased by 1 first.

```json
{ "type": "RESOLVE_INCIDENT", "incidentSelector": { "elementId": "Task_CallAPI" } }
```

### `ASSERT_VARIABLES`

```json
{
  "type": "ASSERT_VARIABLES",
  "processInstanceSelector": { "processDefinitionId": "expense-approval" },
  "variables": { "approved": true }
}
```

Optional `elementSelector` (local scope), `variableNames` (existence-only check).

> Only assert variables that feed a downstream gateway or DMN — see [§ What not to write](#what-not-to-write).

### `ASSERT_USER_TASK`

State values: `IS_CREATED`, `IS_COMPLETED`, `IS_CANCELED`, `IS_FAILED`. Other optional fields: `assignee`, `candidateGroups`, `priority`, `elementId`, `name`, `dueDate`, `followUpDate`.

```json
{
  "type": "ASSERT_USER_TASK",
  "userTaskSelector": { "taskName": "Review invoice" },
  "state": "IS_CREATED"
}
```

### `ASSERT_PROCESS_INSTANCE_MESSAGE_SUBSCRIPTION`

Asserts that a message subscription exists on a process instance in the given state — useful before a `CORRELATE_MESSAGE` to confirm the engine is actually waiting. State values: `IS_WAITING`, `IS_NOT_WAITING`, `IS_CORRELATED`.

```json
{
  "type": "ASSERT_PROCESS_INSTANCE_MESSAGE_SUBSCRIPTION",
  "processInstanceSelector": { "processDefinitionId": "expense-approval" },
  "messageSelector": { "messageName": "order-paid" },
  "state": "IS_WAITING"
}
```

### `ASSERT_ELEMENT_INSTANCE`

Single-instance variant of `ASSERT_ELEMENT_INSTANCES` — use when the assertion is about exactly one element instance. Optional `amount` (default `1`).

```json
{
  "type": "ASSERT_ELEMENT_INSTANCE",
  "processInstanceSelector": { "processDefinitionId": "expense-approval" },
  "elementSelector": { "elementId": "Task_ManagerReview" },
  "state": "IS_COMPLETED"
}
```

### Selectors

Most instructions accept a selector object instead of a plain id. Fields are mutually exclusive — supply one. Available across selectors (subset depends on the instruction):

| Selector | Fields |
|----------|--------|
| `jobSelector` | `jobType`, `elementId`, `processDefinitionId` |
| `userTaskSelector` | `elementId`, `taskName`, `processDefinitionId` |
| `incidentSelector` | `elementId`, `processDefinitionId` |
| `processInstanceSelector` | `processDefinitionId` |
| `elementSelector` | `elementId`, `elementName` |
| `messageSelector` | `messageName`, `correlationKey` |
| `decisionDefinitionSelector` | `decisionDefinitionId` |

## Segment pattern

A scenario for a non-happy-path segment typically looks like:

1. `CREATE_PROCESS_INSTANCE` — variables chosen to route to the target branch.
2. `ASSERT_ELEMENT_INSTANCES` — the target element reached (`IS_ACTIVE`).
3. `COMPLETE_*` or `THROW_BPMN_ERROR_FROM_JOB` — drive past the element.
4. `ASSERT_ELEMENT_INSTANCES` on the rejoin point — the segment rejoined the common path.
5. Optional final `ASSERT_PROCESS_INSTANCE: IS_COMPLETED` only if the segment runs to an end event.

A segment that rejoins the happy path does **not** need to assert every downstream element again — the happy-path scenario already covers them. This is what keeps the suite minimal.

## What not to write

- `ASSERT_VARIABLE` on a service-task output variable. Out of scope — CPT covers routing, not data correctness.
- Repeated complete-the-final-task tail across every segment. If a segment rejoins the happy path before the tail, end the segment there.
- Copy-paste assertions whose values come from FEEL inside the process. The process already evaluates the FEEL; asserting the same value tests the test, not the process.

## Schema-version reminder

The `$schema` URL pins the CPT instruction grammar version. If you upgrade CPT in `pom.xml`, update the schema URL to match — older URLs may reject newer instruction types.

---

## Java fallback

Java tests are not rendered by Web Modeler — business analysts cannot read them. Default to JSON unless one of these constraints applies:

- The scenario needs a Spring bean mocked (`@MockBean`) — a worker that calls an external system in production.
- Parameterized data tables — same flow, many input rows. `@ParameterizedTest` + `@CsvSource` beats N near-duplicate JSON entries.
- Assertions that don't map to `ASSERT_*` instructions — message correlation timing, specific `incident` payloads, custom `CamundaAssert` matchers.
- Non-deterministic runtime races — `context.when(condition).then(action)` (8.9+) registers background watchers for parallel branch races, ad-hoc tool activation, message vs. timer races. See [test-context.md § Conditional behavior](test-context.md#conditional-behavior-89).
- Setup logic across many tests — `@BeforeAll`, shared fixtures, custom `Duration` assertion timeouts.

The full Java context API surface (`mockJobWorker`, `completeJobOfAdHocSubProcess`, `when().then()`, decision and selector assertions, time control) lives in [test-context.md](test-context.md). The class shape and a worked example follow.

### Class shape

```java
package io.camunda.tests;

import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaSpringProcessTest;
import io.camunda.process.test.api.TestDeployment;
import io.camunda.client.CamundaClient;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
@CamundaSpringProcessTest
@TestDeployment(resources = {
    "processes/expense-approval.bpmn",
    "processes/approval-routing.dmn"
})
public class ExpenseApprovalJavaTest {

    @Autowired private CamundaClient camunda;

    @Test
    void financePath_managerApprovesFinanceApproves() {
        var instance = camunda.newCreateInstanceCommand()
            .bpmnProcessId("expense-approval").latestVersion()
            .variables(java.util.Map.of("amount", 1500, "department", "Marketing"))
            .send().join();

        CamundaAssert.assertThat(instance)
            .hasActiveElements("Task_ManagerReview_Finance");
        // … drive user tasks via the user-task API, then:
        CamundaAssert.assertThat(instance).isCompleted();
    }
}
```

### Helpers

- `CamundaAssert.assertThat(processInstance).hasActiveElements("…")` — equivalent to `ASSERT_ELEMENT_INSTANCES … IS_ACTIVE`.
- `CamundaAssert.assertThat(processInstance).isCompleted()` — equivalent to `ASSERT_PROCESS_INSTANCE … IS_COMPLETED`.
- `CamundaAssert.setAssertionTimeout(Duration.ofMinutes(5))` — bump the polling timeout for slow external workers (LLMs, multi-second connectors). The CPT default is 10s (`CamundaAssert.DEFAULT_ASSERTION_TIMEOUT`).
- `CamundaAssert.assertThatDecision(DecisionSelectors.byId("dish"))` — DMN decision-instance assertion. See [test-context.md § DMN-instance assertions](test-context.md#dmn-instance-assertions) for the full surface (`isEvaluated`, `hasOutput`, `hasMatchedRules`, selector factories `byId`/`byName`/`byProcessInstanceKey`/`byResponse`) and **camunda-dmn** § testing-decisions for what to assert per hit policy.

### Mocking workers

```java
@MockBean private NotificationWorker notificationWorker;

@BeforeEach void stubNotification() {
    when(notificationWorker.send(any())).thenReturn(NotificationResult.ok());
}
```

The mock auto-completes `Task_SendNotification` instead of requiring `COMPLETE_JOB` in JSON.

Same scope rules apply: do not assert produced data values. The Java surface offers richer assertions; that does not change what is in scope for process tests.
