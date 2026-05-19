# Coverage strategy — set-cover, 100% target

A test segment is a slice of process execution between two points. The goal: pick the smallest set of segments whose combined coverage is every element and sequence flow in the BPMN. Plan first, author second. The CPT coverage report at `target/coverage-report/report.html` is the exit gate.

Two ideas drive the strategy:

1. **Predict each candidate's coverage statically** by walking the BPMN forward from the segment's root through its targeted branch to its rejoin or end event. Set membership is known before any test runs.
2. **Greedy set-cover** picks the smallest non-redundant subset. No "author then dedupe" — redundancy never gets authored.

## Step 1 — parse the BPMN

Extract:

- `processId` from `<bpmn:process id="…">`.
- All element IDs and types.
- Every gateway's outgoing flows with their `conditionExpression`, plus the `default` flow.
- Every `<bpmn:boundaryEvent>` (error, timer, escalation, message), the element it attaches to, and the error code / timer / message it catches.
- Every `<zeebe:calledDecision decisionId="…">` and the rules inside the DMN file.
- All end events — distinct ends produce distinct outcomes.

## Step 2 — enumerate candidate segments

Build a candidate list. Walk the model:

| Candidate type | Root | End | Notes |
|----------------|------|-----|-------|
| Each gateway branch (incl. `default`) | The gateway | First rejoin or end event | One candidate per outgoing flow |
| Each DMN rule (incl. `default`) | The business-rule task **or** a standalone `EVALUATE_DECISION` | First rejoin or end event (process-driven) / decision response (standalone) | Process-driven for rules whose inputs map 1:1 to a BPMN gateway; standalone (`EVALUATE_DECISION` + `ASSERT_DECISION`) when the input partition doesn't — isolates the failure cause. See **camunda-dmn** § testing-decisions. |
| Each error boundary event | The activity it attaches to (use `THROW_BPMN_ERROR_FROM_JOB` with matching `errorCode`) | The boundary's outgoing path end event | |
| Each timer / escalation / message boundary | The activity it attaches to | The boundary's outgoing path end event | Timer uses `INCREASE_TIME` past the cycle |
| Each alternate end event | A gateway / branch combination that reaches it | The end event | |
| Multi-instance loop | `CREATE_PROCESS_INSTANCE` with a collection input | First post-loop join | |
| Each inner activity of an `<bpmn:adHocSubProcess>` | The AHSP itself | The activity completing | Inner activities have no inbound sequence flow — they look like dead code to a naive walker but are reachable via dynamic activation. See § Ad-hoc subprocess and tool activation below. |
| Happy path (baseline) | Start event | Most common end event | Choose the most common branch at every gateway and DMN |

For each candidate, **statically predict the visited set**: walk the BPMN forward from root through the chosen branch to the end condition, collecting every element id and sequence flow id along the way. Store as `(name, root, predicted_ids)`.

## Step 3 — greedy set-cover

```text
universe   = {every element id} ∪ {every sequence flow id}
chosen     = []
covered    = ∅

while covered != universe:
    pick candidate c that maximizes |predicted_ids(c) − covered|
    tie-break: shortest path (fewest predicted ids — cheapest to author)
    chosen.append(c)
    covered |= predicted_ids(c)
```

The happy-path candidate usually wins round 1 because it covers the spine. Subsequent rounds pick segments that uniquely add boundary events, alternate branches, or alternate rules.

When two candidates share a root but exercise different failure modes (e.g. boundary fires vs. user task completes normally), greedy set-cover may pick only one. If diagnostic isolation matters more than minimality (you want failures to point at one cause), keep both — flag this as an explicit opt-out, not the default.

## Step 4 — print the plan

```text
Segment plan — expense-approval

  Selected by greedy set-cover (predicted 100% coverage):

  1. MANAGER path — manager approves
     root: Gateway_ApprovalLevel (MANAGER branch via amount=750)
     covers (13): Start, Task_DetermineApproval, Gateway_ApprovalLevel,
                  Flow_Manager, Task_ManagerReview, Gateway_ManagerDecision,
                  Flow_ManagerApproved, Gateway_MergeBeforeNotify, Flow_ToNotify,
                  Task_SendNotification, Flow_ToEnd, EndEvent_1, …
  2. MANAGER path — manager rejects
     root: Gateway_ManagerDecision (reject)
     covers (+1): Flow_ManagerRejected
  3. FINANCE path — manager and finance approve
     root: Gateway_ApprovalLevel (FINANCE branch via amount=1500)
     covers (+3): Task_ManagerReview_Finance, Flow_FinanceManagerApproved,
                  Task_FinanceReview, Flow_FinanceReviewDone, …
  4. FINANCE path — manager rejects
     root: Gateway_FinanceManagerDecision (reject)
     covers (+1): Flow_FinanceManagerRejected
  5. AUTO path — notification fails, error boundary fires
     root: Task_SendNotification (throw NOTIFICATION_FAILED), routes via amount=200
     covers (+4): Flow_Auto, BoundaryEvent_NotifyError, Flow_ErrorEnd, EndEvent_Error
  6. MANAGER path — reminder fires after 24h
     root: Task_ManagerReview + INCREASE_TIME PT25H
     covers (+5): BoundaryEvent_Reminder, Flow_Reminder, Task_SendReminder,
                  Flow_ReminderEnd, EndEvent_Reminder
  7. FINANCE path — reminder2 fires after 24h
     root: Task_ManagerReview_Finance + INCREASE_TIME PT25H
     covers (+5): BoundaryEvent_Reminder2, Flow_Reminder2, Task_SendReminder2,
                  Flow_ReminderEnd2, EndEvent_Reminder2

  Total: 7 segments. Predicted coverage: 38/38 = 100%.
```

Author exactly this list.

## Step 5 — verify against the CPT report

Run `mvn test`. Parse `target/coverage-report/report.html` (the page embeds the full dataset as a `window.COVERAGE_DATA` JSON literal — see SKILL.md for the extractor).

If aggregate runtime coverage equals predicted coverage, done. If it does not, the gap is a **prediction miss** — the static walk for one of the chosen candidates did not match the engine's actual path. Common causes: gateway condition the parser couldn't evaluate, FEEL expression depending on a variable the planner did not set, non-interrupting boundary that creates a parallel branch the walker missed.

Treat misses as planner bugs, not just gaps to patch. Add the missing candidates to chosen, but also fix the prediction rule so the next BPMN does not hit the same miss.

## Ad-hoc subprocess and tool activation

Inner activities of an `<bpmn:adHocSubProcess>` have **no inbound sequence flow** — they are activated dynamically, either declaratively (internal mode, via `activeElementsCollection`) or programmatically (job-worker mode, via the worker's `activateElements` result). A static walker treats them as dead code and drops them from coverage. They are not dead code: the AHSP itself is the entry point, and each inner activity must show up in the segment plan.

**Planner rule.** For every inner activity of an AHSP, add one candidate segment rooted at the AHSP and ending when that inner activity completes. The candidate's predicted set includes the inner activity, its outgoing internal flow (if any), and the AHSP itself.

**Authoring** depends on the AHSP mode (the internal-mode vs. job-worker-mode distinction is covered in **camunda-bpmn**):

- **Internal mode** (no `<zeebe:taskDefinition>` on the AHSP): pass `activeElementsCollection` and any tool inputs as variables on `CREATE_PROCESS_INSTANCE`; each inner activity then becomes a normal job — `COMPLETE_JOB` against `jobSelector.elementId` for each. No outer AHSP job exists.
- **Job-worker mode** (has `<zeebe:taskDefinition>`, e.g. the AI Agent Sub-process connector): the AHSP is itself a job. Stub the agent loop with a Java orchestrator — `context.mockJobWorker(ahsType).withHandler(handler)` returns activation results, and `context.when(condition).then(action)` *(8.9+)* completes each activated tool once it becomes active. A plain `COMPLETE_JOB_AD_HOC_SUB_PROCESS` JSON instruction can drive a single activation cycle but cannot react to per-iteration state.

Worked stub-orchestrator pattern (Java, AI-agent-style AHSP):

```java
context.mockJobWorker("io.camunda.agenticai:aiagent:1").withHandler((client, job) -> {
    // 1. Inspect job variables to decide which tools to activate next.
    // 2. Build an ad-hoc result with .activateElement("Tool_X").variables(...).
    // 3. Mark .completionConditionFulfilled(true) when the agent decides it is done.
});

context
    .when(() -> CamundaAssert.assertThat(processInstance).hasActiveElements("Tool_FetchOrder"))
    .then(() -> context.completeJob(JobSelectors.byElementId("Tool_FetchOrder"),
                                    Map.of("toolCallResult", Map.of("status", "ok"))));
```

Cross-links: **camunda-ai-agents** for the BPMN shape and tool-modelling rules; [authoring.md § COMPLETE_JOB_AD_HOC_SUB_PROCESS](authoring.md#complete_job_ad_hoc_sub_process) for the JSON instruction; [test-context.md § Conditional behavior](test-context.md#conditional-behavior-89) for `when().then()` semantics.

## Anti-patterns

- **Author-then-dedupe.** Authoring one segment per uncovered element and pruning after the loop wastes Maven cycles and adds reviewer noise. Set-cover planning eliminates redundancy at the planning step.
- **Happy-path tail in every segment.** A secondary segment that runs through the entire happy path after rejoining doubles up coverage. End the segment at the first rejoin.
- **Variable-value assertions instead of routing assertions.** A segment that asserts `amount == 750` after the gateway tests Jackson, not the gateway. Assert the element the gateway routed to.
- **One scenario per DMN rule when the rule is on the chosen happy path.** Set-cover already credits the chosen rule. Add scenarios only for other rules.
