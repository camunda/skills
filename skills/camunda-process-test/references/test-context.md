# `CamundaProcessTestContext` — Java API

When a scenario needs more than the JSON instruction set can express, drop to the Java fallback (see [authoring.md § Java fallback](authoring.md#java-fallback)) and use the `CamundaProcessTestContext` that CPT injects into each test. The context is the canonical Java entry point for stubbing workers, fast-forwarding time, mocking sub-decisions, completing jobs, and reacting to runtime conditions.

Version tags below mark features introduced **above the 8.8 floor**; untagged methods are 8.8 baseline.

## Injection

Two equivalent injection styles — pick whichever fits the test class shape.

Field-level autowiring (typical for `@CamundaSpringProcessTest`):

```java
@SpringBootTest
@CamundaSpringProcessTest
public class MyTest {
    @Autowired private CamundaProcessTestContext processTestContext;

    @Test
    void myTest() {
        processTestContext.mockJobWorker("notification").thenComplete();
    }
}
```

Per-test parameter injection (works under both `@CamundaSpringProcessTest` and the plain JUnit `@CamundaProcessTest`):

```java
@Test
void myTest(final CamundaProcessTestContext context) {
    context.mockJobWorker("notification").thenComplete();
}
```

Do not store the context as a static field — the runtime resets it per test.

## Method surface

### Clients and addresses

| Method | Use |
|--------|-----|
| `createClient()` / `createClient(Consumer<CamundaClientBuilder>)` | Build a `CamundaClient` that the runtime closes for you — issue process commands without owning client lifecycle. |
| `getCamundaGrpcAddress()` / `getCamundaRestAddress()` | URIs of the embedded Zeebe runtime — point external clients (HTTP, custom workers) at these in mixed-language test scaffolds. |
| `getConnectorsAddress()` | URI of the in-test Connectors runtime when it is enabled — see [connectors-runtime.md](connectors-runtime.md). |

### Time control

| Method | Use |
|--------|-----|
| `getCurrentTime()` | Current "test clock" — diverges from system time once `increaseTime` / `setTime` is called. |
| `increaseTime(Duration)` | Jump the test clock forward past a timer cycle. Same shape as the JSON `INCREASE_TIME` instruction. |
| `setTime(Instant)` | Pin the test clock to a specific instant — useful when an interval `R/.../P*` cycle anchor matters. |

### Job-worker stubbing

| Method | Use |
|--------|-----|
| `mockJobWorker(jobType) → JobWorkerMockBuilder` | Register a stub worker for `<zeebe:taskDefinition type="…">`. Chain `.thenComplete()`, `.thenThrowBpmnError(code)`, `.withHandler(jobHandler)`. Use when the production worker would call out to a real system. |
| `completeJob(jobType)` / `completeJob(jobType, variables)` | Imperatively complete the next pending job of this type — equivalent to the JSON `COMPLETE_JOB` instruction. |
| `completeJob(JobSelector)` / `completeJob(JobSelector, variables)` *(8.9+)* | Selector-based variant — match by element id, process definition id, process instance key, or job kind. |
| `completeJobWithExampleData(jobType \| JobSelector)` *(8.9+)* | Complete with the BPMN element's `example` data property as the output payload. Used when the BPMN already carries representative test data. |
| `throwBpmnErrorFromJob(jobType, errorCode)` / `(jobType, errorCode, variables)` | Trigger an attached error boundary by throwing the named BPMN error. |
| `throwBpmnErrorFromJob(jobType, errorCode, errorMessage, variables)` *(8.9+)* | 4-arg overload that also sets the error message surfaced on the incident. |
| `throwBpmnErrorFromJob(JobSelector, …)` *(8.9+)* | Selector-based throw — same overloads as `completeJob`. |

### User-task completion

| Method | Use |
|--------|-----|
| `completeUserTask(elementId)` / `completeUserTask(elementId, variables)` | Complete a Camunda user task by BPMN id. |
| `completeUserTask(UserTaskSelector, [variables])` *(8.9+)* | Selector-based — match by element id, task name, process instance key, or process definition id. |
| `completeUserTaskWithExampleData(elementId \| UserTaskSelector)` *(8.9+)* | Complete using the user task's `example` data property as the output. |

### Ad-hoc sub-process completion *(8.9+)*

| Method | Use |
|--------|-----|
| `completeJobOfAdHocSubProcess(JobSelector, Consumer<CompleteAdHocSubProcessResultStep1>)` | Complete the **job-worker-mode** ad-hoc sub-process job. Inside the consumer call `.activateElement(elementId).variables(...)`, `.completionConditionFulfilled(true)`, and/or `.cancelRemainingInstances(true)` to drive the next loop iteration or close the AHSP. |
| `completeJobOfAdHocSubProcess(JobSelector, variables, Consumer<…>)` | Same, with input variables for the activated tools. |

Required when the BPMN ad-hoc sub-process carries a `<zeebe:taskDefinition type="…">` (job-worker mode — the mode the AI Agent Sub-process connector uses). A plain `COMPLETE_JOB` against the AHSP outer job will hang. See [authoring.md § COMPLETE_JOB_AD_HOC_SUB_PROCESS](authoring.md#complete_job_ad_hoc_sub_process) for the JSON equivalent; the internal-mode vs. job-worker-mode distinction is covered in **camunda-bpmn**.

### User-task listener jobs *(8.9+)*

| Method | Use |
|--------|-----|
| `completeJobOfUserTaskListener(JobSelector, Consumer<CompleteUserTaskJobResultStep1>)` | Complete a user-task listener job (`assignment`/`update`/`complete`/`canceling`). Inside the consumer call `.denied(true).deniedReason(...)` to reject the transition, or `.corrections(c -> c.assignee(...).dueDate(...))` to mutate task attributes before letting the transition proceed. |

### DMN stubbing

| Method | Use |
|--------|-----|
| `mockDmnDecision(decisionId, decisionOutput)` | Replace a real DMN evaluation with a fixed output — isolates BPMN-flow tests from DMN rule changes. `decisionOutput` may be a value, list, or map; pick the shape the DMN would have returned. Pair with `assertThatDecision(...)` in dedicated decision tests; do not assert and mock the same decision in the same scenario. |

### Child-process stubbing

| Method | Use |
|--------|-----|
| `mockChildProcess(childProcessId)` | Replace a called process with a no-op that completes immediately. |
| `mockChildProcess(childProcessId, Map<String, Object> variables)` | Same, with fixed output variables. |
| `mockChildProcess(childProcessId, Function<Map, Map> variablesSupplier)` *(8.9+)* | Supplier overload — output variables computed from the parent's variables at call time. Use when the called process's output depends on per-instance input. |

### Incidents and variables *(8.9+)*

| Method | Use |
|--------|-----|
| `resolveIncident(IncidentSelector)` | Resolve a matching incident; if the incident wraps a job, increases retries by 1 first. Equivalent to the JSON `RESOLVE_INCIDENT` instruction. |
| `updateVariables(ProcessInstanceSelector, variables)` *(8.9+)* | Create or update process-instance-scoped variables mid-test. Use sparingly — driving routing via real instructions is closer to production behavior. |
| `updateLocalVariables(ProcessInstanceSelector, ElementSelector, variables)` *(8.9+)* | Set variables on a specific element's local scope. No JSON equivalent — Java only. |

### Conditional behavior *(8.9+)*

`context.when(condition).then(action)` registers a background watcher that fires `action` (a `Runnable`) once the `condition` (a `BehaviorCondition` — typically a CPT assertion lambda) is met. Use it for **non-deterministic runtime races** that can't be expressed with a linear instruction list — message vs. timer races, parallel branches whose order is undefined, dynamic tool activation inside an ad-hoc sub-process.

```java
context
    .when(() -> CamundaAssert.assertThatUserTask(byTaskName("Wait for confirmation")).isCreated())
    .then(() -> context.completeUserTask(byTaskName("Wait for confirmation"), Map.of("ok", true)));
```

Semantics:

- The condition is **a `Runnable`-like lambda that throws** — typically a `CamundaAssert.assertThat…` call. A satisfied condition completes without throwing; an unsatisfied one throws `AssertionError`.
- The condition is polled in the background until it passes; the action runs once and the registration is exhausted (chain `.then(action2).then(action3)` for multi-step behaviors — the last `then` repeats indefinitely once preceding actions are consumed).
- The condition should **flip from false to true exactly once per intended action**. A condition that stays true forever paired with a single action causes the action to fire once and then go silent — exactly what you want; but pairing the same condition with `.then().then()` will fire each action only when the assertion transitions from failing to passing again.
- Optional `.as("descriptive name")` for log/diagnostic output — use it when several watchers are registered against the same condition family.

Common conditions:

| Condition lambda | Fires when |
|------------------|------------|
| `() -> assertThat(instance).hasActiveElements("Wait")` | The element becomes active. |
| `() -> assertThat(instance).isCompleted()` | The process instance reaches completion. |
| `() -> assertThatUserTask(byTaskName("Approve")).isCreated()` | A user task with that name exists in `CREATED` state. |

Cross-link: ad-hoc tool orchestration is the most common use case — see [coverage-strategy.md § Ad-hoc subprocess and tool activation](coverage-strategy.md#ad-hoc-subprocess-and-tool-activation) for the pattern.

## DMN-instance assertions

`CamundaAssert.assertThatDecision(DecisionSelectors.byId("…"))` runs against a real or mocked decision evaluation. Selector factories:

| `DecisionSelectors` factory | Picks |
|-----------------------------|-------|
| `byId(decisionDefinitionId)` | Decision-instance(s) for the given decision id. |
| `byName(decisionName)` | By human-readable name. |
| `byProcessInstanceKey(key)` | All decisions evaluated inside a specific process instance — combine with `byId` chaining when several decisions run. |
| `byResponse(EvaluateDecisionResponse)` | The result of a standalone `camundaClient.newEvaluateDecisionCommand()…` — for decision tests that don't run inside a process. |

Assertion methods on the returned `DecisionInstanceAssert`: `.isEvaluated()`, `.hasOutput(value)`, `.hasMatchedRules(int…)`, `.hasNotMatchedRules(int…)`, `.hasNoMatchedRules()`. Rule numbers are 1-based ordinals in rule order — what to assert per hit policy lives in **camunda-dmn**.

## Selector factories (Java)

| Class | Common factories |
|-------|------------------|
| `JobSelectors` | `byJobType(String)`, `byElementId(String)`, `byProcessDefinitionId(String)`, `byProcessInstanceKey(long)`, `byJobKind(JobKind)` |
| `UserTaskSelectors` | `byElementId(String)`, `byTaskName(String)`, `byTaskName(String, long pi)`, `byProcessInstanceKey(long)`, `byProcessDefinitionId(String)` |
| `IncidentSelectors` | `byElementId(String)`, `byProcessDefinitionId(String)`, `byProcessInstanceKey(long)` |
| `ProcessInstanceSelectors` | `byKey(long)`, `byProcessId(String)`, `byParentProcessInstanceKey(long)` |
| `ElementSelectors` | `byId(String)`, `byName(String)`, `byElementType(ElementInstanceType)`, `byElementInstanceKey(long)`, `byState(ElementInstanceState)` |

Selector classes are 8.8 baseline; new factory overloads land alongside the methods that consume them (e.g. `JobSelector` lookups expanded in 8.9 to support `completeJob(JobSelector)`).
