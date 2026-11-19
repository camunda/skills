// Second e2e: test_bpmn scenario replay in the view + user edit → get_bpmn_edits.
import { chromium } from "playwright";
import { Client } from "@modelcontextprotocol/client";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

const host = process.argv[2] ?? "http://localhost:8090";
const fixture = process.argv[3];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
await page.goto(host);
await page.waitForTimeout(1500);
await page.locator("select").nth(1).selectOption("test_bpmn");
await page.locator("textarea").first().fill(
  JSON.stringify({
    path: fixture,
    steps: [
      { action: "start", variables: { orderId: "A-1" } },
      { action: "completeJob", jobType: "check-credit", variables: { creditOk: true } },
      { action: "expect", active: ["Task_Review"] },
    ],
  }),
);
await page.locator('button[type="submit"]').click();
await page.waitForTimeout(3000);
const app = page.frames().at(-1);
await app.waitForSelector(".outcomes", { timeout: 15000 });
console.log("scenario panel:", (await app.textContent(".outcomes")).replace(/\s+/g, " "));
console.log("active after replay:", await app.locator(".tok-active").count());
await page.screenshot({ path: "/tmp/bpmn-scenario.png" });

// Edit: back to model tab, rename via direct edit of a label using modeling API isn't reachable;
// emulate by deleting an element with keyboard.
await app.click('button[data-tab="model"]');
await app.click('[data-element-id="EndEvent_Done"]');
await page.keyboard.press("Delete");
await page.waitForTimeout(2500);
console.log("dirty:", await app.isVisible("#dirty"), "lint:", await app.textContent("#lint-badge"));

const c = new Client({ name: "e2e", version: "0" });
await c.connect(new StreamableHTTPClientTransport(new URL("http://localhost:3001/mcp")));
const r = await c.callTool({ name: "get_bpmn_edits", arguments: { path: fixture } });
const t = r.content[0].text;
console.log("get_bpmn_edits:", t.split("\n")[0], "| EndEvent removed:", !t.includes('id="EndEvent_Done"'));
await page.screenshot({ path: "/tmp/bpmn-edited.png" });
await browser.close();
await c.close();
