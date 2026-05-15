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
- Setup logic across many tests — `@BeforeAll`, shared fixtures, custom `Duration` assertion timeouts.

### Class shape

```java
package io.camunda.tests;

import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaSpringProcessTest;
import io.camunda.process.test.api.TestDeployment;
import io.camunda.zeebe.client.ZeebeClient;
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

    @Autowired private ZeebeClient zeebe;

    @Test
    void financePath_managerApprovesFinanceApproves() {
        var instance = zeebe.newCreateInstanceCommand()
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
- `CamundaAssert.setAssertionTimeout(Duration.ofMinutes(5))` — bump the default 10s polling timeout for slow external workers.

### Mocking workers

```java
@MockBean private NotificationWorker notificationWorker;

@BeforeEach void stubNotification() {
    when(notificationWorker.send(any())).thenReturn(NotificationResult.ok());
}
```

The mock auto-completes `Task_SendNotification` instead of requiring `COMPLETE_JOB` in JSON.

Same scope rules apply: do not assert produced data values. The Java surface offers richer assertions; that does not change what is in scope for process tests.
