---
name: camunda-bpmn
description: Creates, edits, and validates BPMN 2.0 process diagrams for Camunda 8 (Zeebe). This skill should be used when creating new BPMN processes, modifying existing process diagrams, adding elements (tasks, gateways, events, subprocesses), configuring Zeebe extensions, or validating BPMN XML.
---

# Camunda BPMN Modeling

Create and edit executable BPMN 2.0 processes for Camunda 8.8+. Generates valid XML with Zeebe extensions and diagram coordinates.

## Prerequisites

- Camunda 8.8+ cluster (local via c8run, SaaS, or Self-Managed)
- c8ctl CLI installed and configured (`c8 add profile`) — provides `c8 bpmn lint`

## Cross-References

- **camunda-feel**: Use for FEEL expressions in gateway conditions, input/output mappings, timer definitions
- **camunda-forms**: Use for creating Camunda Form JSON schemas linked to user tasks
- **camunda-connectors**: Use for configuring pre-built connectors (REST, Slack, Kafka, etc.) via element templates
- **camunda-deploy**: Use for deploying BPMN to a Camunda cluster via c8ctl

## Instructions

### XML Structure

Every BPMN file requires these namespaces:

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
- **User Task**: Human interaction. Requires `<zeebe:userTask/>` (8.5+) and `<zeebe:formDefinition formId="..."/>`. Assign with `<zeebe:assignmentDefinition candidateGroups="..."/>`.
- **Service Task**: Automated work. Requires `<zeebe:taskDefinition type="..." retries="3"/>`. The type must exactly match worker registration (case-sensitive).
- **Script Task**: Inline FEEL expression. Uses `<zeebe:script expression="=..." resultVariable="..."/>`.
- **Business Rule Task**: DMN evaluation. Uses `<zeebe:calledDecision decisionId="..." resultVariable="..."/>`.
- Name tasks with **verb + object** pattern: "Review invoice", "Send notification"

**Gateways:**
- **Exclusive (XOR)**: Exactly one path taken. Set `default` attribute for the fallback flow. Label condition flows.
- **Parallel (AND)**: All paths taken concurrently. Always use a matching join gateway to synchronize.
- **Inclusive (OR)**: One or more paths. Also requires a matching join.
- Always fix fake-join warnings from `c8 bpmn lint` — join gateways must match their fork type.

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

### Validation

After generating or editing BPMN XML, always validate:

```bash
c8 bpmn lint path/to/process.bpmn
```

`c8 bpmn lint` auto-detects the Camunda execution platform version from the BPMN file and applies sensible Camunda defaults. If a `.bpmnlintrc` is present in the project, it is used instead. You can also pipe BPMN via stdin:

```bash
cat process.bpmn | c8 bpmn lint
```

Fix ALL errors and warnings, especially:
- **no-overlapping-elements**: Adjust DI coordinates for proper spacing
- **fake-join**: Ensure gateways properly join/synchronize flows
- **label-required**: All labeled elements must have names

Re-validate until clean.

### Hygiene

- Self-close empty elements
- Keep unique, descriptive IDs
- Include BPMN DI section for visual layout (see `references/layout-rules.md`)
- Always include `<bpmn:incoming>` and `<bpmn:outgoing>` flow references on elements

## References

For detailed reference material, read from `references/`:
- `references/element-catalog.md` — complete BPMN element types with Camunda/Zeebe attributes (events, tasks, gateways, subprocesses)
- `references/zeebe-extensions.md` — input/output mappings, variable scoping, task definitions, form definitions, secrets
- `references/layout-rules.md` — DI coordinate management, element sizes, spacing rules for diagram layout
