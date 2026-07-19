name: camunda-bpmn
description: |
  Use this skill to create, edit, and validate BPMN 2.0 process diagrams for Camunda 8 (Zeebe).

  Use for: new BPMN processes, modifying existing diagrams, adding tasks/gateways/events/subprocesses, configuring Zeebe extensions (taskDefinition, ioMapping, loop characteristics), validating BPMN XML.

  Do not use for: writing FEEL expressions inside BPMN (use camunda-feel), designing form schemas (use camunda-forms), or deploying and running processes (use camunda-process-mgmt).

  **Workflow skill** — multi-step BPMN authoring. Covers c8ctl bpmn lint for validation.
name: camunda-bpmn
description: |
  Use this skill to create, edit, and validate BPMN 2.0 process diagrams for Camunda 8 (Zeebe).

  Use for: new BPMN processes, modifying existing diagrams, adding tasks/gateways/events/subprocesses, configuring Zeebe extensions (taskDefinition, ioMapping, loop characteristics), validating BPMN XML.

  Do not use for: writing FEEL expressions inside BPMN (use camunda-feel), designing form schemas (use camunda-forms), or deploying and running processes (use camunda-process-mgmt).

  **Workflow skill** — use bpmn-cli for BPMN modeling and c8ctl for linting.
---

# Camunda BPMN Modeling

Create and edit executable Camunda 8.8+ BPMN with `bpmn-cli`. It owns semantic
inspection, descriptor-aware mutations, serialization, and deterministic layout.
Never hand-edit BPMN XML, including Diagram Interchange (DI).

## Prerequisites

- `bpmn-cli` installed and on `PATH`
- c8ctl CLI installed and configured (`c8ctl add profile`) — provides `c8ctl bpmn lint`

## Cross-References

- **camunda-feel**: Use for FEEL expressions in gateway conditions, input/output mappings, timer definitions
- **camunda-dmn**: Use for authoring the DMN decision behind a business rule task
- **camunda-forms**: Use for creating Camunda Form JSON schemas linked to user tasks
- **camunda-connectors**: Use for configuring pre-built connectors via c8ctl element templates
- **camunda-development**: Use to decide whether a service task needs a connector or job worker
- **camunda-job-workers**: Use to implement the handler a `zeebe:taskDefinition` activates
- **camunda-connectors-development**: Use to build custom connectors
- **camunda-process-test**: Use for embedded-engine process tests
- **camunda-process-mgmt**: Use for deployment and instance operations
- **camunda-ai-agents**: Use when modeling an AI agent

## Modeling Workflow

### Discover before changing

Use JSON output for every agent decision. Discover IDs, `$type` values, exact
references, and writable descriptor property names; do not infer them from XML.

```bash
bpmn-cli inspect process.bpmn --json
bpmn-cli inspect process.bpmn --process Process_1 --json
bpmn-cli inspect process.bpmn --element Task_Review --json
bpmn-cli trace process.bpmn --from Gateway_Risk --json
```

For a new process, begin from a valid BPMN starter supplied by the host or
project, then use the same workflow. Do not create BPMN XML by hand.

### Preview, apply, verify

1. Discover the Edit v1 request schema when needed:

   ```bash
   bpmn-cli edit --schema --json
   ```

2. Write a request containing only `add`, `remove`, `replace`, and `move`
   operations. Every operation needs explicit `expect` assertions.

3. Preview without writing BPMN and review the `planHash`, generated IDs,
   derived effects, semantic changes, and layout:

   ```bash
   bpmn-cli edit process.bpmn --request edit.json --json > preview.json
   ```

4. Apply only the exact reviewed hash. Prefer a separate output file when the
   environment supports reviewable artifacts; use in-place apply only when the
   host stages changes separately from the user’s source:

   ```bash
   PLAN_HASH=$(node -e "console.log(JSON.parse(require('fs').readFileSync('preview.json', 'utf8')).planHash)")
   bpmn-cli edit process.bpmn --request edit.json --apply "$PLAN_HASH" --json
   ```

5. Run the lint loop and fix every error and warning:

   ```bash
   c8ctl bpmn lint process.bpmn
   ```

`bpmn-cli edit` lays out BPMN by default. Do not use `--no-layout` unless a
host explicitly requires a DI-free artifact. Do not create, preserve, or repair
coordinates, shapes, edges, bounds, or waypoints directly.

### Connector and element-template changes

Use **camunda-connectors** and retain `c8ctl` as the sole element-template
authority. Run `c8ctl element-template sync` once per session, then discover,
inspect, and apply the template with `c8ctl element-template apply -i`.

After template application, re-run `bpmn-cli inspect` before previewing any
later edit: the source changed, so any earlier `planHash` is stale. Always close
the complete BPMN change with `c8ctl bpmn lint`.

### Recover from edit errors

| Error code | Required action |
| --- | --- |
| `STALE_PLAN` | Re-inspect and preview again. Do not reuse the hash. |
| `EDIT_PRECONDITION_FAILED` | Re-inspect the target and correct the request; do not weaken `expect`. |
| `EDIT_BPMN_STRUCTURE_INVALID` | Change the requested semantics; do not bypass structural validation. |
| `EXTERNAL_REFERENCE_CONFLICT` | Inspect all references and make required changes explicit. |
| `EDIT_TARGET_NOT_FOUND` | Discover the actual ID or create and alias it in an earlier operation. |
| `PROFILE_ERROR` | Use the correct moddle descriptor and avoid namespace collisions. |

## Core Modeling Rules

**Start and end events:** Every path starts at a Start Event and reaches an End
Event. Use None for ordinary starts, Message for external triggers, and Timer
for schedules.

**Tasks:** Model one atomic action per task and use verb-plus-object names.

- User tasks use `<zeebe:userTask />`, a `<zeebe:formDefinition formId="X" />`,
  and appropriate assignment. `formId="X"` requires an `X.form` deliverable via
  **camunda-forms**.
- Service tasks require a `<zeebe:taskDefinition type="..." retries="3" />`.
  The type exactly matches the worker registration. Apply connector templates
  through **camunda-connectors**; do not model their generated mappings manually.
- Script tasks use `<zeebe:script expression="=..." resultVariable="..." />`.
- Business rule tasks use `<zeebe:calledDecision decisionId="X" resultVariable="..." />`.
  `decisionId="X"` requires an `X.dmn` deliverable via **camunda-dmn**.

**Gateways:** XOR gateways have one default flow and labeled conditional flows.
AND and OR forks have matching joins. Fix fake joins reported by lint.

**FEEL:** Conditions, timers, and mappings use an `=` prefix. Validate anything
beyond a simple variable reference with **camunda-feel**.

**IDs:** Use descriptive PascalCase, such as `ReviewInvoice`,
`AmountExceedsLimit`, and `Flow_ToApproval`. Preserve unrelated IDs.

See [references/zeebe-extensions.md](references/zeebe-extensions.md) for
variable scoping, mappings, task definitions, forms, and secrets; see
[references/element-catalog.md](references/element-catalog.md) for BPMN and
Zeebe element details.

## Behavioural Validation

Lint validates structural and policy concerns, not worker availability or all
runtime behavior. After a clean lint, use **camunda-process-test** or
**camunda-process-mgmt** to validate the intended execution path.

# Camunda BPMN Modeling

Create and edit executable BPMN 2.0 processes for Camunda 8.8+. Generates valid XML with Zeebe extensions and diagram coordinates.

## Copilot DI-Free Mode

When the host explicitly states that **Copilot DI-free mode** is active, it provides a staged
semantic BPMN working copy and guarantees a deterministic layout and final validation boundary.
In this mode:

- Do not create, retain, edit, or repair `<bpmndi:BPMNDiagram>` content.
- Do not emit coordinates, dimensions, or waypoints.
- Make semantic XML edits only and preserve unchanged element IDs.
- Do not run `c8ctl bpmn lint` during the agent loop; the host restores DI and runs final validation.
- Do not treat a semantic edit as a finished user-visible BPMN artifact. The host returns the
  fully laid-out candidate for review.

This mode applies only when the host has declared it. Otherwise follow the standalone workflow
below, including complete BPMN DI and the lint loop.

## Prerequisites

- Camunda 8.8+ cluster (local via c8run, SaaS, or Self-Managed)
- c8ctl CLI installed and configured (`c8ctl add profile`) — provides `c8ctl bpmn lint`
- **c8ctl ≥ 3.2.0** for `bpmn format`. If the command is unavailable, ask the user to upgrade: `npm install -g @camunda8/cli`

## Cross-References

- **camunda-feel**: Use for FEEL expressions in gateway conditions, input/output mappings, timer definitions
- **camunda-dmn**: Use for authoring the DMN decision behind a business rule task — `<zeebe:calledDecision decisionId="..." resultVariable="..."/>`
- **camunda-forms**: Use for creating Camunda Form JSON schemas linked to user tasks
- **camunda-connectors**: Use for configuring pre-built connectors (REST, Slack, Kafka, etc.) via element templates
- **camunda-development**: Use to decide whether a service task should be backed by an OOTB connector, a custom connector, or a job worker
- **camunda-job-workers**: Use to implement the handler code that a service task's `zeebe:taskDefinition type` activates
- **camunda-connectors-development**: Use to build a custom connector (JSON-only template or Java SDK) that attaches to a service task or event element
- **camunda-process-test**: Use for testing processes against an embedded Zeebe engine
- **camunda-process-mgmt**: Use for deploying to a cluster and running instances
- **camunda-ai-agents**: Use when modeling an AI agent — ad-hoc subprocess hosting tools driven by the AI Agent connector

## Instructions

### XML Structure

When writing a BPMN file from scratch, follow the canonical bpmn-js style — single-line `<bpmn:definitions>`, two-space indent, no blank lines between siblings, `<el />` self-closing form. Otherwise any round-trip through Camunda Modeler, Web Modeler, or `c8ctl element-template apply` reformats the file, breaking `Edit` matches and adding diff noise. Rules and a worked skeleton: [references/canonical-style.md](references/canonical-style.md).

The `zeebe` namespace, `isExecutable="true"`, and `modeler:executionPlatform="Camunda Cloud"` are mandatory — without them, Camunda won't recognize the process correctly.

Outside Copilot DI-free mode, the `<bpmndi:BPMNDiagram>` block is mandatory, not optional polish: `c8ctl bpmn lint` flags missing DI (`no-bpmndi`) as an error, and Modeler can't render a process without it. Every `<bpmn:process>` flow element needs a matching `<bpmndi:BPMNShape>`, every `<bpmn:sequenceFlow>` a `<bpmndi:BPMNEdge>`. Coordinates, sizes, and waypoint conventions: [references/layout-rules.md](references/layout-rules.md). Note that Zeebe deploys a DI-less BPMN happily — the missing DI surfaces only at lint and in Modeler, so don't rely on a successful deploy as evidence the file is well-formed.

### Symbol Encoding

Always encode special characters in XML attribute values:
- `<` → `&lt;`, `>` → `&gt;`, `&` → `&amp;`, `"` → `&quot;`, `'` → `&apos;`

### Core Modeling Rules

**Start/End Events:**
- Every path starts with a Start Event (no incoming flows) and reaches an End Event (no outgoing flows)
- Use None start event for most processes; Message for external triggers; Timer for scheduled execution

**Tasks** — one atomic action per task:
- **User Task**: Human interaction. Use the Camunda user task implementation: include `<zeebe:userTask />` and link the form via `<zeebe:formDefinition formId="X" />`. Assign with `<zeebe:assignmentDefinition candidateGroups="..." />`. Setting `formId="X"` makes `X.form` a required deliverable — author it via **camunda-forms** in the same step, or flag the gap explicitly in your final message. `c8ctl bpmn lint` checks the attribute is present, not that the file resolves. Do NOT write the deprecated job-worker variant (no `<zeebe:userTask />`, `formKey` instead of `formId`) — see [references/zeebe-extensions.md](references/zeebe-extensions.md) § Form Definition.
- **Service Task**: Automated work. Requires `<zeebe:taskDefinition type="..." retries="3" />`. The type must exactly match worker registration (case-sensitive). When backed by an out-of-the-box connector, apply the template via **camunda-connectors** — don't hand-write the connector input mappings.
- **Script Task**: Inline FEEL expression. Uses `<zeebe:script expression="=..." resultVariable="..." />`.
- **Business Rule Task**: DMN evaluation. Uses `<zeebe:calledDecision decisionId="X" resultVariable="..." />`. `decisionId="X"` makes the corresponding `X.dmn` a required deliverable — author it via **camunda-dmn**.
- Name tasks with **verb + object** pattern: "Review invoice", "Send notification"

**Gateways:**
- **Exclusive (XOR)**: Exactly one path taken. Set `default` attribute for the fallback flow. Label condition flows.
- **Parallel (AND)**: All paths taken concurrently. Always use a matching join gateway to synchronize.
- **Inclusive (OR)**: One or more paths. Also requires a matching join.
- Fix fake-join warnings from `c8ctl bpmn lint` — join gateways must match their fork type.

**Sequence Flows:**
- Conditions use FEEL expressions with `=` prefix:
  ```xml
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">=amount &gt; 1000</bpmn:conditionExpression>
  ```

**FEEL Expressions in BPMN** — all FEEL must be prefixed with `=`:
- Gateway conditions: `=riskLevel = "HIGH"`
- Timer durations: `="PT7D"` (plain `PT7D` is rejected)
- Input/output mappings: `=customer.name`

Anything beyond a simple variable reference (function calls, operators, context literals, `for` / `every` / `some`) — validate via **camunda-feel** before committing.

**IDs**: Use descriptive PascalCase — `ReviewInvoice`, `AmountExceedsLimit`, `Flow_ToApproval`

### Input/Output Mappings

Create local variables and control variable propagation:

```xml
<zeebe:ioMapping>
  <!-- Input: create local variable from parent scope -->
  <zeebe:input source="=customer.name" target="customerName" />
  <!-- Output: propagate local result to parent scope -->
  <zeebe:output source="=result.status" target="paymentStatus" />
</zeebe:ioMapping>
```

See [references/zeebe-extensions.md](references/zeebe-extensions.md) for detailed variable scoping, propagation rules, and examples.

### Working with Existing BPMN Files

BPMN files can be large. Follow these rules:
1. **Use Grep to find elements** — never read entire files unnecessarily
2. **Use Edit for modifications** — locate the exact section with Grep first, then make precise edits
3. **Read specific sections only** — use offset/limit when needed

### Hygiene

- Follow canonical bpmn-js style — see [references/canonical-style.md](references/canonical-style.md)
- Self-close empty elements with `<el />` (single space before `/>`)
- Keep unique, descriptive IDs
- Outside Copilot DI-free mode, include BPMN DI for visual layout (see [references/layout-rules.md](references/layout-rules.md))
- Include `<bpmn:incoming>` and `<bpmn:outgoing>` flow references on elements

### Lint loop — structural exit gate

Outside Copilot DI-free mode, a BPMN edit is **not structurally done** until `c8ctl bpmn lint` reports zero errors AND zero warnings. Treat this as the closing structural step of every BPMN task — generation, modification, refactor, or merge. In Copilot DI-free mode, the host owns this final gate after it restores DI.

1. Run the linter against the file you touched:

   ```bash
   c8ctl bpmn lint path/to/process.bpmn
   ```

   `c8ctl bpmn lint` auto-detects the Camunda execution platform version from the BPMN file and applies sensible Camunda defaults. If a `.bpmnlintrc` is present in the project, it is used instead. Stdin also works: `cat process.bpmn | c8ctl bpmn lint`.

2. If output is non-empty, fix every reported issue and run the linter again. Common categories:
   - **no-overlapping-elements** — adjust DI coordinates per [references/layout-rules.md](references/layout-rules.md) spacing rules
   - **fake-join** — make join gateways match their fork type (XOR forks → XOR joins, AND forks → AND joins)
   - **label-required** — name every labeled element
   - **no-disconnected** — ensure every element is on a complete start-to-end path
   - **no-implicit-split** — exclusive gateway outgoing flows need conditions + a default
   - **superfluous-gateway** — drop pass-through gateways with one in, one out

3. Loop until the linter is clean. Do not declare the task structurally done while warnings remain — silently-failing BPMN deploys to the cluster and surfaces as runtime incidents.

If a warning is genuinely a false positive, suppress it explicitly in a project-level `.bpmnlintrc` and flag the suppression in your final message — never silently ignore.

### Behavioural validation

Lint catches structure, not runtime behaviour (FEEL errors, missing workers, unreachable end events). After lint is clean, validate by **running the process**: prefer **camunda-process-test** for embedded-engine feedback without a cluster, or fall back to **camunda-process-mgmt** to deploy and run an instance.

## References

For detailed reference material, read from `references/`:
- [element-catalog.md](references/element-catalog.md) — complete BPMN element types with Camunda/Zeebe attributes (events, tasks, gateways, subprocesses)
- [zeebe-extensions.md](references/zeebe-extensions.md) — input/output mappings, variable scoping, task definitions, form definitions, secrets
- [layout-rules.md](references/layout-rules.md) — DI coordinate management, element sizes, spacing rules for diagram layout
- [canonical-style.md](references/canonical-style.md) — canonical bpmn-js XML style: tag layout, attribute order, self-closing form, why hand-formatting drifts
