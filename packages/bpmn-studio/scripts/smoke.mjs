// Headless end-to-end check: spawn the stdio server, list tools, read the UI
// resource, lint + show + test the fixture, drive the server-side engine.
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixture = path.join(root, "fixtures/order-approval.bpmn");
const client = new Client({ name: "smoke", version: "0" });
await client.connect(new StdioClientTransport({ command: "node", args: [path.join(root, "dist/index.js"), "--stdio"], cwd: root }));

const call = async (name, args) => {
  const r = await client.callTool({ name, arguments: args });
  return r;
};
const ok = (m) => console.log("✓", m);

const { tools } = await client.listTools();
const names = tools.map((t) => t.name).sort();
console.log("tools:", names.join(", "));
for (const t of ["show_bpmn", "lint_bpmn", "test_bpmn", "get_bpmn_edits"]) assert(names.includes(t), t);
const show = tools.find((t) => t.name === "show_bpmn");
assert.equal(show._meta?.ui?.resourceUri, "ui://bpmn/studio.html");
ok("tool metadata");

const res = await client.readResource({ uri: "ui://bpmn/studio.html" });
const html = res.contents[0].text;
assert(html.length > 10000, "html bundle present");
console.log(`  ui bundle ${(html.length / 1024).toFixed(0)} KB, mime ${res.contents[0].mimeType}`);
ok("ui resource");

let r = await call("lint_bpmn", { path: fixture });
console.log(" ", r.content[0].text.split("\n")[0]);
assert.equal(r.structuredContent.errorCount, 0, r.content[0].text);
const brokenXml = '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:modeler="http://camunda.org/schema/modeler/1.0" modeler:executionPlatform="Camunda Cloud" modeler:executionPlatformVersion="8.8.0" id="d" targetNamespace="x"><bpmn:process id="p" isExecutable="true"><bpmn:serviceTask id="t"/></bpmn:process></bpmn:definitions>';
r = await call("lint_bpmn", { xml: brokenXml });
assert(r.structuredContent.errorCount > 0);
ok(`lint catches broken diagram (${r.structuredContent.errorCount} errors)`);
r = await call("test_bpmn", { xml: brokenXml, steps: [{ action: "start" }] });
assert(r.isError && r.content[0].text.startsWith("Not run") && r.structuredContent?.mode === "model", r.content[0].text);
ok("test_bpmn lint gate refuses diagrams with errors");

r = await call("show_bpmn", { path: fixture });
assert.equal(r.structuredContent.mode, "edit");
const docId = r.structuredContent.docId;
ok("show_bpmn " + docId);

r = await call("test_bpmn", {
  path: fixture,
  steps: [
    { action: "start" },
    { action: "completeJob", jobType: "check-credit", variables: { creditOk: false } },
    { action: "expect", active: ["Task_Review"] },
    { action: "completeUserTask", elementId: "Task_Review" },
    { action: "completeJob", jobType: "ship-order" },
    { action: "expect", completed: true, passed: ["Task_Review"] },
  ],
});
console.log(r.content[0].text.replace(/^/gm, "  "));
assert(r.structuredContent.scenario.passed);
r = await call("test_bpmn", {
  path: fixture,
  steps: [{ action: "start" }, { action: "completeJob", jobType: "check-credit", variables: { creditOk: true } }, { action: "expect", notPassed: ["Task_Review"], active: ["Task_Ship"] }],
});
assert(r.structuredContent.scenario.passed, r.content[0].text);
ok("test_bpmn both branches");

// A completed instance's final variables stay assertable (Zeebe drops them from process
// state on completion; the engine's read model keeps them). Root-scope only: variables
// local to a sub-process scope must NOT surface as instance variables.
const finalFixture = path.join(root, "fixtures/final-variables.bpmn");
r = await call("lint_bpmn", { path: finalFixture });
assert.equal(r.structuredContent.errorCount, 0, r.content[0].text);
const finalRun = (expectVariables) => [
  { action: "start", variables: { in: "x" } },
  { action: "completeJob", jobType: "inner", variables: { innerOut: "i" } },
  { action: "completeJob", jobType: "work", variables: { out: "y" } },
  { action: "expect", completed: true, noIncidents: true, variables: expectVariables },
];
r = await call("test_bpmn", { path: finalFixture, steps: finalRun({ in: "x", innerOut: "i", out: "y" }) });
assert(r.structuredContent.scenario.passed, r.content[0].text);
ok("final variables assertable after completion");
r = await call("test_bpmn", { path: finalFixture, steps: finalRun({ localSub: 42 }) });
assert(!r.structuredContent.scenario.passed && /variable localSub/.test(r.content[0].text), r.content[0].text);
ok("sub-process-local variables are not instance variables");

// app-only tools are callable (host would hide them from the model)
r = await call("ui_engine", { cmd: { op: "deploy", xml: (await import("node:fs")).readFileSync(fixture, "utf8") } });
assert(r.structuredContent.ok, r.content[0].text);
const sid = r.structuredContent.sessionId;
r = await call("ui_engine", { sessionId: sid, cmd: { op: "createInstance", processId: "order-approval" } });
assert.deepEqual(r.structuredContent.snapshot.activeElementIds, ["Task_Check"]);
ok("server-side engine session");

r = await call("ui_sync", { docId, xml: "<edited/>", note: "user ran a test: passed" });
r = await call("get_bpmn_edits", { docId });
assert(r.content[0].text.includes("<edited/>") && r.content[0].text.includes("NOT saved"));
ok("draft sync → get_bpmn_edits");

r = await call("save_bpmn", { path: "/etc/evil.bpmn", xml: "<x/>" });
assert(r.isError && /outside/.test(r.content[0].text));
r = await call("save_bpmn", { path: "fixtures/out/.smoke.bpmn", docId });
assert(!r.isError, r.content[0].text);
(await import("node:fs")).rmSync(path.join(root, "fixtures/out"), { recursive: true });
ok("save_bpmn writes inside root only");

await client.close();
console.log("\nsmoke OK");
