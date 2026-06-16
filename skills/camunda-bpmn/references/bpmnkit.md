# bpmnkit recipes

Patterns for the `@bpmnkit/core` authoring path (Path A in SKILL.md). The minimal
create-and-export flow lives in SKILL.md; this file covers gateways, events, the
post-export compatibility step, and editing existing files.

## Setup

bpmnkit is a Node.js library. Any of these works — pick what the environment has:

```bash
# Node + npm (baseline): install into a scratch dir, then `node script.mjs`
mkdir -p bpmnkit && cd bpmnkit && npm install @bpmnkit/core   # any writable dir works

# Bun: auto-installs on run, no separate install step
bun run script.mjs                       # import { Bpmn } from "@bpmnkit/core"

# Deno: self-contained, no node_modules — use an npm: specifier in the script
deno run --allow-read --allow-write script.mjs   # import { Bpmn } from "npm:@bpmnkit/core"
```

The directory is just a scratch location for the script and its `node_modules`; the
output BPMN goes wherever the task needs it (write with an absolute path).

## Camunda 8.8 compatibility (post-export)

bpmnkit's exporter stamps `modeler:executionPlatformVersion="8.6.0"` and does not emit
`<zeebe:userTask />`. For Camunda 8.8+, fix both after `Bpmn.export()`:

```javascript
let xml = Bpmn.export(defs);
// Bump the stamped platform version to the 8.8 floor (match your cluster if higher).
xml = xml.replace(/modeler:executionPlatformVersion="[^"]*"/, 'modeler:executionPlatformVersion="8.8.0"');
// Emit Camunda (Zeebe) user tasks for tasks with a linked form — bpmnkit omits this.
xml = xml.replace(/<zeebe:formDefinition /g, "<zeebe:userTask />\n        <zeebe:formDefinition ");
writeFileSync("/path/to/output/process.bpmn", xml);
```

For a user task **without** a form, add `<bpmn:extensionElements><zeebe:userTask /></bpmn:extensionElements>`
with the Edit tool after generation. Setting `formId` makes `formId.form` a required
deliverable — author it via **camunda-forms**, or flag the gap in your final message.

(Parse/export preserves an existing `executionPlatformVersion` and existing
`<zeebe:userTask />` elements, so the bump only matters for freshly created processes.)

## Exclusive gateway (XOR)

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

FEEL condition prefix `=` is required — `b.condition("= amount > 1000")`, not
`"amount > 1000"`. Encode `>` as-is in the JS string; bpmnkit escapes it to `&gt;` in
the XML attribute.

## Parallel gateway (AND)

```javascript
.parallelGateway("Fork", { name: "Notify in parallel" })
.branch("email", b => b.serviceTask("SendEmail", { name: "Send email", taskType: "send-email" }).connectTo("Join"))
.branch("sms",   b => b.serviceTask("SendSms",   { name: "Send SMS",   taskType: "send-sms"   }).connectTo("Join"))
.parallelGateway("Join", { name: "Notifications sent" })
```

## Timer boundary event

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

## Editing existing BPMN

Two approaches, depending on the edit:

**Structural edits — operations API.** Parse, `compactify`, apply atomic operations
(`rename` / `update` / `insert` / `delete` / `add_flow` / `delete_flow` / `redirect_flow`),
then `expand` and export. References are stable element IDs:

```javascript
import { Bpmn, compactify, expand, applyOperations } from "@bpmnkit/core";
import { readFileSync, writeFileSync } from "fs";

const compact = compactify(Bpmn.parse(readFileSync("process.bpmn", "utf-8")));
// Insert "Notify" between W and E: drop the old connector, add the node, rewire.
const we = compact.processes[0].flows.find(f => f.from === "W" && f.to === "E");
const edited = applyOperations(compact, [
  { op: "delete_flow", id: we.id },
  { op: "insert", element: { id: "Notify", type: "serviceTask", name: "Notify", jobType: "notify" }, after: "W" },
  { op: "add_flow", from: "W", to: "Notify" },
  { op: "add_flow", from: "Notify", to: "E" },
]);
writeFileSync("process.bpmn", Bpmn.export(expand(edited)));
```

`insert ... after` only **positions** the node in document order — it does not rewire
flows. To splice a node into a flow you must delete the old connector and add the two new
flows yourself (skipping that leaves a fake-join + implicit-start, which lint catches).
Inserted nodes get auto-placed DI; existing element coordinates are preserved.

**Small textual edits — manual Edit.** A bare `Bpmn.parse → Bpmn.export` round-trip
preserves DI coordinates exactly, but reserializes the whole file (reorders elements,
normalizes whitespace and self-closing tags). For a one-attribute change to a
Modeler-authored file that produces a large, noisy diff — the manual Edit path
(Path B in SKILL.md) gives a cleaner one.

## Auto-layout

`.withAutoLayout()` (builder) and `Bpmn.autoLayout(xml)` (standalone, takes and returns
XML) both **regenerate every coordinate from scratch**, discarding any manual layout. Use
them on new processes, or to repair a broken/missing diagram — never by default when
editing a file whose layout should be kept. For edits, prefer the operations API above,
which lays out only the new nodes.
