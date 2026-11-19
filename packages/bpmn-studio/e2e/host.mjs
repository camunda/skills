// Drive the reference MCP Apps host (ext-apps basic-host) with Playwright:
// call a tool, find the app iframe, take screenshots, exercise the test studio.
// usage: node e2e/host.mjs [hostUrl] [outDir]
import { chromium } from "playwright";
import path from "node:path";

const host = process.argv[2] ?? "http://localhost:8090";
const out = process.argv[3] ?? "/tmp/bpmn-e2e";
const fixture = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../fixtures/order-approval.bpmn");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const logs = [];
page.on("console", (m) => logs.push(`[host ${m.type()}] ${m.text()}`));
page.on("frameattached", () => {});
browser.contexts()[0].on("console", () => {});

await page.goto(host);
await page.waitForTimeout(1500);
const selects = page.locator("select");
// tool select is the second select
const toolSelect = selects.nth(1);
await toolSelect.selectOption("show_bpmn");
await page.locator("textarea").first().fill(JSON.stringify({ path: fixture }));
await page.locator('button[type="submit"]').click();

// nested: host page → sandbox proxy iframe → app iframe
let appFrame;
for (let i = 0; i < 40 && !appFrame; i++) {
  await page.waitForTimeout(500);
  appFrame = page.frames().find((f) => f !== page.mainFrame() && f.url() !== "about:blank" && f.parentFrame() !== page.mainFrame());
  appFrame ??= page.frames().find((f) => f.name() === "" && f !== page.mainFrame() && f.url().startsWith("about:srcdoc"));
}
const frames = page.frames().map((f) => f.url().slice(0, 60));
console.log("frames:", frames);
const app = page.frames().find((f) => f !== page.mainFrame() && f.childFrames().length === 0 && f.parentFrame() && f.parentFrame() !== page.mainFrame()) ?? page.frames().at(-1);

await app.waitForSelector(".djs-element", { timeout: 20000 });
await page.waitForTimeout(1500);
console.log("title:", await app.textContent("#title"), "| lint:", await app.textContent("#lint-badge"));
console.log("lint list:", (await app.textContent("#lint-list"))?.slice(0, 200));
console.log("shapes:", await app.locator(".djs-shape").count());
await page.screenshot({ path: `${out}-model.png` });

// switch to test studio
await app.click('button[data-tab="test"]');
await app.waitForSelector("#engine-kind");
await page.waitForTimeout(800);
console.log("engine:", await app.textContent("#engine-kind"));
await app.click("text=▶ Start");
await app.waitForSelector("text=check-credit", { timeout: 10000 });
await app.locator(".card textarea").first().fill('{"creditOk": false}');
await app.click(".card >> text=Complete");
await app.waitForSelector("text=Complete task", { timeout: 10000 });
console.log("active tok:", await app.locator(".tok-active").count(), "taken flows:", await app.locator(".flow-taken").count());
await page.screenshot({ path: `${out}-test.png` });
await app.click("text=Complete task");
await app.waitForSelector(".card >> text=ship-order", { timeout: 10000 });
await app.click(".card >> text=Complete");
await app.waitForSelector(".state-completed", { timeout: 10000 });
console.log("instance completed ✓");
console.log("log:", (await app.textContent(".log"))?.slice(0, 400));
await page.screenshot({ path: `${out}-done.png` });

console.log(logs.filter((l) => /error|warn|bpmn-studio/i.test(l)).slice(0, 15).join("\n"));
await browser.close();
