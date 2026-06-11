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

- c8ctl CLI installed and configured (`c8ctl add profile`) — provides `c8ctl bpmn lint`
- **c8ctl ≥ 3.2.0** for `bpmn format`. If the command is unavailable, ask the user to upgrade: `npm install -g @camunda8/cli`
- Node.js 18+ recommended — enables the bpmnkit authoring path (check with `node --version`)

Authoring and linting are offline — no cluster needed. A Camunda 8.8+ cluster (local via c8run, SaaS, or Self-Managed) is only required for the deploy-and-run step, which is delegated to **camunda-process-mgmt** / **camunda-process-test**.

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

`@bpmnkit/core` is a Node.js library that builds valid BPMN 2.0 XML — mandatory Camunda 8 namespace headers, Zeebe extensions, and DI coordinates — from a fluent API, at far fewer tokens than hand-writing XML. It runs under Node (baseline), Bun, or Deno.

Install into a scratch dir (`npm install @bpmnkit/core`), then run your script with `node script.mjs`. Write the output to an absolute path so it lands in the right place regardless of the script's working directory. Setup variants (Bun/Deno) are in [references/bpmnkit.md](references/bpmnkit.md).

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

**Always pass `{ name: "..." }`** to start events, end events, and gateways — without it `c8ctl bpmn lint` reports `label-required`.

**Two post-export fixes for Camunda 8.8+:** the exporter stamps `executionPlatformVersion="8.6.0"` and omits `<zeebe:userTask />`. Bump the version and inject the user-task element after `Bpmn.export()` — see [references/bpmnkit.md](references/bpmnkit.md), which also covers gateways, events, and editing existing files.

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

Once lint reports zero issues the file is complete — no need to read it back.

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

- [bpmnkit.md](references/bpmnkit.md) — bpmnkit setup, recipes (gateways, events), 8.8 compatibility, editing
- [element-catalog.md](references/element-catalog.md)
- [zeebe-extensions.md](references/zeebe-extensions.md)
- [layout-rules.md](references/layout-rules.md)
- [canonical-style.md](references/canonical-style.md)
