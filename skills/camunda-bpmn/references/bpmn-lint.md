# BPMN lint playbook

Use this when a task asks for "lint and fix BPMN" across one file or many files.

## Scope modes

- **Single file**: lint one `.bpmn` file directly.
- **Directory**: discover `.bpmn` files recursively and lint each file.

Skip these directories during discovery: `.git`, `node_modules`, `target`, `build`, `.gradle`, `.mvn`, `.idea`, `.settings`, `.snapshots`.

```bash
find <target-dir> -type d \( -name .git -o -name node_modules -o -name target -o -name build -o -name .gradle -o -name .mvn -o -name .idea -o -name .settings -o -name .snapshots \) -prune -o -type f -name '*.bpmn' -print
```

## Run + fix loop

1. Run `c8ctl bpmn lint` on each target file.
2. Parse each report line by extracting these fields (without assuming exact spacing): `elementId`, `severity`, `message`, `ruleId`.
3. Apply targeted XML edits for each issue (never whole-file rewrites).
4. Re-run lint on the same target set.
5. Repeat until all files are clean.

## `bpmnlint:recommended` rule map

| Rule | Fix |
|---|---|
| `ad-hoc-sub-process` | Remove start/end events inside the ad-hoc sub-process; ensure intermediate catch events have outgoing sequence flow. |
| `conditional-flows` | Add a condition expression to non-default outgoing flows, or define a `default` flow. |
| `end-event-required` | Add an End Event to each process/sub-process path. |
| `event-based-gateway` | Ensure at least two outgoing flows and no conditional sequence flows from the event-based gateway. |
| `event-sub-process-typed-start-event` | Add an event definition (message/timer/error/etc.) to the event-sub-process start event. |
| `fake-join` | Add a proper join gateway before the element with multiple incoming flows. |
| `global` | Ensure global Error/Escalation/Message/Signal elements are named, referenced, and unique per type. |
| `label-required` | Add a descriptive `name` label. |
| `link-event` | Name link-event definitions and pair each link throw with a matching catch in the same scope. |
| `no-bpmndi` | Add missing BPMNDI shapes/edges so each flow node and sequence flow has diagram data. |
| `no-complex-gateway` | Replace Complex Gateway with explicit Exclusive/Parallel structure. |
| `no-disconnected` | Connect the element into a valid start-to-end flow. |
| `no-duplicate-sequence-flows` | Remove duplicate flow between the same source and target. |
| `no-gateway-join-fork` | Split mixed join/fork behavior into separate gateways. |
| `no-implicit-end` | Add an explicit End Event. |
| `no-implicit-split` | Add an explicit gateway before multiple outgoing flows. |
| `no-implicit-start` | Add an explicit Start Event. |
| `no-inclusive-gateway` | Replace Inclusive Gateway with explicit Parallel/Exclusive routing if possible. |
| `no-overlapping-elements` | Move DI bounds/waypoints so elements do not overlap. |
| `single-blank-start-event` | Keep exactly one blank start event per scope where that rule applies. |
| `single-event-definition` | Use at most one event definition per event; split mixed semantics. |
| `start-event-required` | Add a Start Event. |
| `sub-process-blank-start-event` | Remove event definition from a sub-process start event; it must be blank. |
| `superfluous-gateway` | Remove pass-through gateways with one incoming and one outgoing flow. |
| `superfluous-termination` | Replace unnecessary Terminate End Events with normal End Events. |
