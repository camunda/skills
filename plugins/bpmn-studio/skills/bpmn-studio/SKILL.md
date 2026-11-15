---
name: bpmn-studio
description: |
  Use when the user asks to create, design, show, review, edit, or test a BPMN process / workflow diagram, and the bpmn-studio MCP tools (show_bpmn, lint_bpmn, test_bpmn) are available. Pairs with the camunda-bpmn skill: camunda-bpmn tells you how to write correct Camunda 8 BPMN; this skill tells you how to show it to the user, lint it, test it, and pick up their edits.
---

# BPMN Studio (MCP App)

The `bpmn-studio` MCP server gives you an interactive bpmn.io modeler and a test studio (running the nanobpm WASM engine) that render **inside the chat** in hosts that support MCP Apps (Claude Desktop / claude.ai, ChatGPT, VS Code). In terminal hosts (Claude Code, Codex CLI) the same tools return text — lint reports and test traces — so the loop still works without a picture.

## Tools

| Tool | Use |
|---|---|
| `lint_bpmn {path \| xml}` | Same rules as `c8ctl bpmn lint` (bpmnlint:recommended + camunda-compat for the declared `modeler:executionPlatformVersion`). Use it when c8ctl is not installed. |
| `show_bpmn {path \| xml, path?}` | Open the diagram in the interactive view. With `xml` + `path`, the view's **Save** writes to `path`. Returns a `docId`. |
| `test_bpmn {path \| xml, steps[]}` | Run a scripted scenario on the in-memory engine: `start`, `completeJob`, `throwError`, `failJob`, `completeUserTask`, `message`, `signal`, `advanceTime`, `expect`. Lints first and **refuses to run diagrams with lint errors** (warnings are fine). In UI hosts it also opens the test studio replaying the run. |
| `get_bpmn_edits {docId \| path}` | Fetch the diagram as the user left it in the view (edits are not on disk until they press Save). |
| `save_bpmn {path, xml \| docId}` | Write a .bpmn file (inside the server root). For hosts without their own file tools, e.g. Claude Desktop. |

## Workflow

1. **Author** the process following the **camunda-bpmn** skill (executable process, Zeebe extensions, full DI with coordinates, `modeler:executionPlatformVersion`).
2. **Lint** until clean: `c8ctl bpmn lint` if available, otherwise `lint_bpmn`. Fix every error; fix warnings unless the user agreed otherwise.
3. **Write** the file (your file tools, or `save_bpmn` when you have none).
4. **Show** it: `show_bpmn {path}`. Tell the user they can edit it in place, and use **Test** to click through it.
5. **Test** every path: one `test_bpmn` scenario per gateway branch / boundary event, with `expect` steps (see the tool schema: active, completed, variables, noIncidents, ...). Report which passed.
6. **Collaborate**: when the user says they changed the diagram (or a message from the view arrives with a note), call `get_bpmn_edits` and work from that XML. Don't overwrite their edits with an older version.

## Scenario example

```json
{ "path": "order.bpmn", "steps": [
  { "action": "start", "processId": "order-approval", "variables": { "orderId": "A-1" } },
  { "action": "completeJob", "jobType": "check-credit", "variables": { "creditOk": false } },
  { "action": "expect", "active": ["Task_Review"] },
  { "action": "completeUserTask", "elementId": "Task_Review" },
  { "action": "completeJob", "jobType": "ship-order" },
  { "action": "expect", "completed": true }
]}
```

## Notes

- The engine is a fast in-memory test engine, not a Camunda cluster. Connectors, real workers and forms don't run; complete their jobs yourself in the scenario. Deploy to a real cluster with the camunda-bpmn / c8ctl flow when the user wants that.
- Keep diagrams readable in the view: left-to-right layout, 150–200px between shapes, labelled gateways and flows.
