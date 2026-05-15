# Coverage strategy — segment-based, 100% target

A test segment is a slice of process execution between two points. The strategy: cover the spine with one happy-path segment, then add the minimum number of secondary segments to exercise every remaining element. Each secondary segment starts at the nearest upstream decision point and ends as soon as it rejoins the happy path or hits an end event.

The exit gate is the CPT coverage report at `target/camunda-process-test/coverage/` — every element must be visited at least once.

## Step 1 — parse the BPMN

Extract:

- `processId` from `<bpmn:process id="…">`.
- All element IDs and types. Treat the **happy path** as the sequence of elements traversed by the most common branch at every gateway and the most common rule in every DMN.
- Every gateway's outgoing flows with their `conditionExpression`, plus the `default` flow.
- Every `<bpmn:boundaryEvent>` (error, timer, escalation, message), the element it attaches to, and the error code / timer / message it catches.
- Every `<zeebe:calledDecision decisionId="…">` and the rules inside the DMN file.
- All end events — distinct ends produce distinct outcomes.

## Step 2 — happy-path segment

One scenario, start event → most common end event, choosing the most common branch at every gateway and the most common rule in every DMN. This seeds coverage of:

- The start event
- All elements on the spine
- One branch of every gateway on the spine
- One rule of every DMN on the spine
- The chosen end event

## Step 3 — enumerate uncovered elements

Walk the BPMN element list, subtract the happy-path visited set, and produce the to-cover list.

## Step 4 — pick a minimal segment per uncovered element

For each uncovered element, the rules:

| Element type | Root the segment at | End the segment when |
|--------------|---------------------|----------------------|
| Non-happy gateway branch | The gateway itself (variables chosen at `CREATE_PROCESS_INSTANCE` to route this way) | The branch's next merge / join with the happy path, or the next end event reached |
| `default` gateway flow | The gateway | First rejoin or end event |
| Non-happy DMN rule | The business-rule task (variables chosen to satisfy that rule's input entries) | First rejoin or end event |
| `default` DMN rule | The business-rule task | First rejoin or end event |
| Error boundary event | The service / user task it attaches to (use `THROW_BPMN_ERROR_FROM_JOB` with the matching `errorCode`) | The boundary's outgoing path end event |
| Timer boundary event | The element it attaches to (advance time via the cluster clock if the segment must wait) | The boundary's outgoing path end event |
| Escalation / message boundary | The element it attaches to | The boundary's outgoing path end event |
| Alternate end event | A gateway / branch combination that reaches it | The end event |
| Multi-instance loop element | A `CREATE_PROCESS_INSTANCE` with collection input that triggers the loop | First post-loop join |

Pick **one** segment per uncovered element. Do not write a segment that re-tests an element already covered by the happy path or another secondary segment.

## Step 5 — print the segment plan

Before authoring any JSON, print:

```text
Segment plan — expense-approval

  Happy path: amount=200, dept=Engineering → AUTO → Notification → End
              covers: Start, DMN, Task_SendNotification, EndEvent_Done
                      Gateway_Routing (AUTO branch)

  Secondary segments:
    1. MANAGER branch — amount=750
       root: Gateway_Routing (MANAGER), ends: Task_SendNotification (rejoin)
       covers: Task_ManagerReview, DMN rule MANAGER
    2. FINANCE branch — amount=1500, both approve
       root: Gateway_Routing (FINANCE), ends: Task_SendNotification (rejoin)
       covers: Task_ManagerReview_Finance, Task_FinanceReview, DMN rule FINANCE
    3. FINANCE — manager rejects
       root: Task_ManagerReview_Finance, ends: Task_SendNotification (rejoin)
       covers: Gateway_ManagerDecision_Finance (Reject branch)
    4. notification error boundary
       root: Task_SendNotification (throw NOTIFICATION_FAILED)
       covers: BoundaryEvent_NotifyError, EndEvent_Error

  Total: 1 + 4 = 5 segments. Predicted coverage: 100%.
```

## Step 6 — verify against the CPT report

Run `mvn test`. Parse `target/camunda-process-test/coverage/coverage.json` (or open the HTML report). For each uncovered element, return to step 4 and add one segment.

The loop terminates only when the report shows 100% element coverage.

## Anti-patterns

- **Happy-path tail in every segment.** If a secondary segment rejoins the spine before the tail, end the segment at the rejoin. The happy-path scenario already covers the tail.
- **One segment per gateway, ignoring downstream elements.** If a non-happy branch carries unique elements (its own user task, a different end event), the segment must cover them — pick the rejoin point accordingly.
- **Variable-value assertions instead of routing assertions.** A segment that asserts `amount == 750` after the gateway tests Jackson, not the gateway. Assert the element the gateway routed to.
- **One scenario per DMN rule when the rule is on the happy path.** The happy-path scenario already exercises one rule. Add scenarios only for *other* rules.
