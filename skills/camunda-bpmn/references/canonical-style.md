# Canonical BPMN style

BPMN files round-trip through the bpmn-js / bpmn-moddle serializer whenever they're saved by Camunda Modeler (Desktop), Web Modeler, or `c8ctl element-template apply`. The serializer canonicalizes whitespace, attribute order, and certain element shapes — any hand-formatting that diverges gets reformatted on first save.

Write BPMN in canonical form up front. Then Modeler saves produce empty diffs (just the real semantic change), and `c8ctl element-template apply` doesn't churn the file.

## Rules

- **`<bpmn:definitions>` is one line.** All `xmlns:*` declarations first, in this order: `bpmn`, `bpmndi`, `dc`, `di`, `xsi`, `zeebe`, `modeler`. Then `id`, then `targetNamespace`, then `modeler:executionPlatform` and `modeler:executionPlatformVersion`.
- **Two-space indent** per nesting level. No tabs.
- **No blank lines** between sibling elements.
- **Self-closing empty elements use a single space before `/>`**: `<zeebe:userTask />`, not `<zeebe:userTask/>`. Applies to every empty element including `<zeebe:taskDefinition … />`, `<zeebe:input … />`, `<dc:Bounds … />`, `<di:waypoint … />`.
- **Multi-attribute extension elements stay on one line** if they fit reasonably.
- **Inside `<bpmndi:BPMNShape>` for tasks**, include `<bpmndi:BPMNLabel />` (empty self-closing). Events don't need it unless labelled.
- **Single space between attributes**, no column alignment on multi-attribute tags like `<bpmn:sequenceFlow>`.

## Skeleton

```xml
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:zeebe="http://camunda.org/schema/zeebe/1.0" xmlns:modeler="http://camunda.org/schema/modeler/1.0" id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn" modeler:executionPlatform="Camunda Cloud" modeler:executionPlatformVersion="8.8.0">
  <bpmn:process id="MyProcess" isExecutable="true">
    <bpmn:serviceTask id="DoWork" name="Do work">
      <bpmn:extensionElements>
        <zeebe:taskDefinition type="do-work" retries="3" />
      </bpmn:extensionElements>
    </bpmn:serviceTask>
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="MyProcess">
      <bpmndi:BPMNShape id="DoWork_di" bpmnElement="DoWork">
        <dc:Bounds x="240" y="80" width="100" height="80" />
        <bpmndi:BPMNLabel />
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
```

## Canonicalizing with `c8ctl bpmn format`

`c8ctl bpmn format` runs a bpmn-moddle round-trip — the same pass that Modeler and `c8ctl element-template apply` execute on save:

```bash
c8ctl bpmn format process.bpmn         # print canonical XML to stdout
c8ctl bpmn format -i process.bpmn      # rewrite in place
cat process.bpmn | c8ctl bpmn format   # read from stdin (stdout only; -i requires a file path)
```

Use it to canonicalize a hand-authored file before the first `Edit` call, or to normalize output from an external tool. After running `format -i`, re-read the file — the round-trip may reorder attributes or normalize whitespace, making prior string matches stale.

## Why it matters

- **`Edit` stays reliable.** `Edit` matches `old_string` byte-for-byte. After any Modeler save, `c8ctl element-template apply`, or `c8ctl bpmn format` call, a hand-formatted file gets canonicalized and the agent's mental model goes stale — every edit then needs a re-read first.
- **Diffs read clean.** A Modeler save reformats a non-canonical file. Subsequent PR diffs mix the semantic change with whitespace and attribute-reorder churn, hiding what actually changed.
