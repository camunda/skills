---
name: camunda-bpmn
description: |
  Use this skill to create, edit, and validate BPMN 2.0 process diagrams for Camunda 8 (Zeebe).

  Use for: new BPMN processes, modifying existing diagrams, adding tasks/gateways/events/subprocesses, configuring Zeebe extensions (taskDefinition, ioMapping, loop characteristics), validating BPMN XML.

  Do not use for: writing FEEL expressions inside BPMN (use camunda-feel), designing form schemas (use camunda-forms), or deploying and running processes (use camunda-process-mgmt).

  **Workflow skill** — multi-step BPMN authoring. Covers c8ctl bpmn lint for validation.
---

# Camunda BPMN Modeling

Create and edit executable BPMN 2.0 processes for Camunda 8.8+.

## Prerequisites

- c8ctl CLI installed and configured (`c8ctl add profile`) — provides `c8ctl bpmn lint`
- **c8ctl ≥ 3.2.0** for `bpmn format`. If the command is unavailable, ask the user to upgrade: `npm install -g @camunda8/cli`
- Node.js 18+ recommended — enables the bpmnkit authoring path (check with `node --version`)

## Authoring Path

Check for Node.js first:

```bash
node --version   # ≥ 18 → use bpmnkit  |  not found → manual XML
```

| Node.js? | Path | Best for |
|---|---|---|
| Yes | **bpmnkit** (`@bpmnkit/core`) | New processes, structural edits |
| No | **Manual XML** | Small edits to existing files, no Node.js |

## Path A — bpmnkit (primary)

`@bpmnkit/core` generates valid BPMN 2.0 XML with mandatory Camunda 8 namespace headers, Zeebe extensions, and DI coordinates via its auto-layout engine.

### Setup

```bash
mkdir -p /tmp/bpmnkit && cd /tmp/bpmnkit && npm install @bpmnkit/core
```

Write your script in that directory (`generate.mjs`) and run it with `node generate.mjs`. Write the output BPMN to wherever the task needs it — use an absolute path so the file ends up in the right place regardless of the script's working directory.

### Minimal pattern

```javascript
import { Bpmn } from "@bpmnkit/core";
import { writeFileSync } from "fs";

const defs = Bpmn.createProcess("my-process", "My Process")
  .startEvent("Start", { name: "Start" })
  .serviceTask("DoWork", { name: "Do work", taskType: "my-worker" })
  .endEvent("End", { name: "Done" })
  .withAutoLayout()
  .build();

writeFileSync("/path/to/output/process.bpmn", Bpmn.export(defs));
```

**Always pass `{ name: "..." }` to start events, end events, and gateways** — without it, `c8ctl bpmn lint` reports `label-required` errors.

### User task caveat

bpmnkit does not emit `<zeebe:userTask />` automatically. After `Bpmn.export()`, inject it for user tasks that have a linked form:

```javascript
xml = xml.replace(/<zeebe:formDefinition /g, "<zeebe:userTask />\n        <zeebe:formDefinition ");
```

For user tasks without a form, add `<bpmn:extensionElements><zeebe:userTask /></bpmn:extensionElements>` with the Edit tool after generation.

Setting `formId` makes `formId.form` a required deliverable — author it via **camunda-forms**, or flag the gap in your final message.

### Exclusive gateway (XOR)

```javascript
.exclusiveGateway("Check", { name: "Amount exceeds limit?" })
.branch("high", b => b.condition("= amount > 1000")
  .serviceTask("ApproveManually", { name: "Approve manually", taskType: "manual-approval" })
  .connectTo("Join")
)
.branch("standard", b => b.defaultFlow()
  .serviceTask("AutoApprove", { name: "Auto-approve", taskType: "auto-approval" })
  .connectTo("Join")
)
.exclusiveGateway("Join", { name: "Approved" })
```

FEEL condition prefix `=` is required — `b.condition("= amount > 1000")`, not `"amount > 1000"`. Encode `>` as-is in the JS string; bpmnkit escapes it to `&gt;` in the XML attribute.

### Parallel gateway (AND)

```javascript
.parallelGateway("Fork", { name: "Notify in parallel" })
.branch("email", b => b.serviceTask("SendEmail", { name: "Send email", taskType: "send-email" }).connectTo("Join"))
.branch("sms",   b => b.serviceTask("SendSms",   { name: "Send SMS",   taskType: "send-sms"   }).connectTo("Join"))
.parallelGateway("Join", { name: "Notifications sent" })
```

### Timer boundary event

```javascript
.userTask("ReviewTask", { name: "Review" })
.boundaryEvent("Timeout", {
  attachedTo: "ReviewTask",
  name: "5-min timeout",
  timerDuration: "PT5M",
  cancelActivity: true,
})
.serviceTask("Escalate", { name: "Escalate", taskType: "escalate" })
.endEvent("Escalated", { name: "Escalated" })
.element("ReviewTask")          // return cursor to the main path
.endEvent("Done", { name: "Done" })
```

### Editing existing BPMN

```javascript
import { Bpmn } from "@bpmnkit/core";
import { readFileSync, writeFileSync } from "fs";

const defs = Bpmn.parse(readFileSync("process.bpmn", "utf-8"));
// inspect or modify defs...
writeFileSync("process.bpmn", Bpmn.export(defs));
```

Parse/export round-trips are lossless for bpmnkit-generated files. For Modeler-authored files with non-standard structure (e.g. missing `id` on `<definitions>`), fall back to manual Edit.

## Path B — Manual XML

For small textual edits to existing BPMN, or when Node.js is unavailable. Follow the canonical bpmn-js style; any round-trip through Modeler or `c8ctl element-template apply` reformats the file otherwise, breaking Edit matches.

Mandatory on every file: `xmlns:zeebe`, `isExecutable="true"`, `modeler:executionPlatform="Camunda Cloud"`, and a `<bpmndi:BPMNDiagram>` block with a shape per flow element and an edge per sequence flow.

References for manual authoring:
- [canonical-style.md](references/canonical-style.md) — XML formatting, attribute order, self-closing form
- [element-catalog.md](references/element-catalog.md) — element types with Zeebe attributes
- [zeebe-extensions.md](references/zeebe-extensions.md) — task definitions, form links, IO mappings
- [layout-rules.md](references/layout-rules.md) — DI coordinates, element sizes, spacing rules

## Lint gate (both paths)

**A BPMN edit is not done until lint reports zero errors and zero warnings:**

```bash
c8ctl bpmn lint path/to/process.bpmn
```

`c8ctl bpmn lint` auto-detects the execution platform version from the BPMN file. Stdin also works: `cat process.bpmn | c8ctl bpmn lint`.

Fix every issue and re-run. Common categories:

- **label-required** — add `name` to the element
- **fake-join** — match join gateway type to its fork (XOR fork → XOR join, AND fork → AND join)
- **no-bpmndi** — add the `<bpmndi:BPMNDiagram>` section
- **no-overlapping-elements** — adjust coordinates per [references/layout-rules.md](references/layout-rules.md)
- **no-disconnected** — every element must lie on a complete start-to-end path
- **no-implicit-split** — exclusive gateway outgoing flows need conditions + a default

Suppress a genuine false positive in a project-level `.bpmnlintrc` and note the suppression in your final message.

## Behavioural validation

Lint catches structure, not runtime behaviour. After lint passes, validate by running the process: **camunda-process-test** (embedded engine) or **camunda-process-mgmt** (deploy and start an instance).

## Cross-References

- **camunda-feel**: FEEL expressions in gateway conditions, input/output mappings, timer definitions
- **camunda-dmn**: DMN decision behind a business rule task — `<zeebe:calledDecision decisionId="..." resultVariable="..."/>`
- **camunda-forms**: Camunda Form JSON schemas linked to user tasks via `formId`
- **camunda-connectors**: Pre-built connectors via element templates — apply with `c8ctl element-template apply`
- **camunda-development**: Decide whether a service task uses an OOTB connector, custom connector, or job worker
- **camunda-job-workers**: Implement the handler code for a service task's `taskDefinition type`
- **camunda-connectors-development**: Build a custom connector attached to a service or event element
- **camunda-process-test**: Test processes against an embedded Zeebe engine
- **camunda-process-mgmt**: Deploy to a cluster and run instances
- **camunda-ai-agents**: Model an AI agent with an ad-hoc subprocess and the AI Agent connector

## References

- [element-catalog.md](references/element-catalog.md)
- [zeebe-extensions.md](references/zeebe-extensions.md)
- [layout-rules.md](references/layout-rules.md)
- [canonical-style.md](references/canonical-style.md)
