---
name: camunda-bpmn
description: |
  Use this skill to create, edit, and validate BPMN 2.0 process diagrams for Camunda 8 (Zeebe).

  Use for: new BPMN processes, modifying existing diagrams, adding tasks/gateways/events/subprocesses, configuring Zeebe extensions (taskDefinition, ioMapping, loop characteristics), validating BPMN XML.

  Do not use for: writing FEEL expressions inside BPMN (use camunda-feel), designing form schemas (use camunda-forms), or deploying and running processes (use camunda-process-mgmt).

  **Workflow skill** — multi-step BPMN authoring. Covers c8ctl bpmn lint for validation.
---

# Camunda BPMN Modeling

Create and edit executable BPMN 2.0 processes for Camunda 8.8+. Generates valid XML with Zeebe extensions and diagram coordinates.

## Prerequisites

- Camunda 8.8+ cluster (local via c8run, SaaS, or Self-Managed)
- c8ctl CLI installed and configured (`c8ctl add profile`) — provides `c8ctl bpmn lint`

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
- **camunda-ai-agent**: Use when modeling an AI agent — ad-hoc subprocess hosting tools driven by the AI Agent connector

## Instructions

### XML Structure

**Example** — every BPMN file requires these namespaces:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions
  xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:zeebe="http://camunda.org/schema/zeebe/1.0"
  xmlns:modeler="http://camunda.org/schema/modeler/1.0"
  modeler:executionPlatform="Camunda Cloud"
  modeler:executionPlatformVersion="8.8.0"
  targetNamespace="http://bpmn.io/schema/bpmn">

  <bpmn:process id="MyProcess" isExecutable="true">
    <!-- elements -->
  </bpmn:process>

  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="MyProcess">
      <!-- shapes and edges -->
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
```

The `zeebe` namespace, `isExecutable="true"`, and `modeler:executionPlatform="Camunda Cloud"` are mandatory. Without them, Camunda won't recognize the process correctly.

### Symbol Encoding

Always encode special characters in XML attribute values:
- `<` → `&lt;`, `>` → `&gt;`, `&` → `&amp;`, `"` → `&quot;`, `'` → `&apos;`

### Core Modeling Rules

**Start/End Events:**
- Every path starts with a Start Event (no incoming flows) and reaches an End Event (no outgoing flows)
- Use None start event for most processes; Message for external triggers; Timer for scheduled execution

**Tasks** — one atomic action per task:
- **User Task**: Human interaction. Use the Camunda user task implementation: include `<zeebe:userTask/>` and link the form via `<zeebe:formDefinition formId="..."/>`. Assign with `<zeebe:assignmentDefinition candidateGroups="..."/>`. Do NOT write the deprecated job-worker variant (no `<zeebe:userTask/>`, `formKey` instead of `formId`) — see `references/zeebe-extensions.md` § Form Definition.
- **Service Task**: Automated work. Requires `<zeebe:taskDefinition type="..." retries="3"/>`. The type must exactly match worker registration (case-sensitive).
- **Script Task**: Inline FEEL expression. Uses `<zeebe:script expression="=..." resultVariable="..."/>`.
- **Business Rule Task**: DMN evaluation. Uses `<zeebe:calledDecision decisionId="..." resultVariable="..."/>`.
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

See `references/zeebe-extensions.md` for detailed variable scoping, propagation rules, and examples.

### Working with Existing BPMN Files

BPMN files can be large. Follow these rules:
1. **Use Grep to find elements** — never read entire files unnecessarily
2. **Use Edit for modifications** — locate the exact section with Grep first, then make precise edits
3. **Read specific sections only** — use offset/limit when needed

### Hygiene

- Self-close empty elements
- Keep unique, descriptive IDs
- Include BPMN DI section for visual layout (see `references/layout-rules.md`)
- Include `<bpmn:incoming>` and `<bpmn:outgoing>` flow references on elements

### Lint loop — structural exit gate

A BPMN edit is **not structurally done** until `c8ctl bpmn lint` reports zero errors AND zero warnings. Treat this as the closing structural step of every BPMN task — generation, modification, refactor, or merge.

1. Run the linter against the file you touched:

   ```bash
   c8ctl bpmn lint path/to/process.bpmn
   ```

   `c8ctl bpmn lint` auto-detects the Camunda execution platform version from the BPMN file and applies sensible Camunda defaults. If a `.bpmnlintrc` is present in the project, it is used instead. Stdin also works: `cat process.bpmn | c8ctl bpmn lint`.

2. If output is non-empty, fix every reported issue and run the linter again. Common categories:
   - **no-overlapping-elements** — adjust DI coordinates per `references/layout-rules.md` spacing rules
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
