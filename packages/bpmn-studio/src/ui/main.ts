import { App, applyDocumentTheme, applyHostFonts, applyHostStyleVariables, type McpUiHostContext } from "@modelcontextprotocol/ext-apps";
import Modeler from "bpmn-js/lib/Modeler";
import { BpmnPropertiesPanelModule, BpmnPropertiesProviderModule, ZeebePropertiesProviderModule } from "bpmn-js-properties-panel";
import ZeebeBehaviorsModule from "camunda-bpmn-js-behaviors/lib/camunda-cloud";
import zeebeModdle from "zeebe-bpmn-moddle/resources/zeebe.json";
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn-embedded.css";
import "@bpmn-io/properties-panel/dist/assets/properties-panel.css";
import "./style.css";
import { createEngine, type EngineClient } from "./engine-client";
import { Studio, type ScenarioPayload } from "./studio";

interface LintIssue {
  id: string;
  message: string;
  category: string;
  rule?: string;
}
interface Payload {
  docId: string;
  path: string | null;
  title: string;
  xml: string;
  mode: "edit" | "test";
  lint?: { errorCount: number; warningCount: number; issues: LintIssue[]; rulesetWarning?: string };
  scenario?: ScenarioPayload;
}

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const app = new App({ name: "BPMN Studio", version: "0.1.0" }, { availableDisplayModes: ["inline", "fullscreen"] } as any);

let doc: Payload | null = null;
let importing = false;
let dirty = false;
let tab: "model" | "test" = "model";
let showProps = false;

const modeler = new Modeler({
  container: "#canvas",
  propertiesPanel: { parent: "#props" },
  additionalModules: [BpmnPropertiesPanelModule, BpmnPropertiesProviderModule, ZeebePropertiesProviderModule, ZeebeBehaviorsModule],
  moddleExtensions: { zeebe: zeebeModdle },
  keyboard: { bindTo: document },
});

let enginePromise: Promise<EngineClient> | null = null;
const getEngine = () => (enginePromise ??= createEngine(app));
const studio = new Studio($("studio"), modeler, getEngine, (summary) => shareWithClaude(summary, true));

// ── helpers ───────────────────────────────────────────────────────────────
let toastTimer: number | undefined;
function toast(msg: string, bad = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = bad ? "bad" : "";
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => t.classList.add("hidden"), 3500);
}

function debounce<A extends unknown[]>(fn: (...a: A) => void, ms: number) {
  let t: number | undefined;
  return (...a: A) => {
    clearTimeout(t);
    t = window.setTimeout(() => fn(...a), ms);
  };
}

async function currentXml(): Promise<string> {
  const { xml } = await modeler.saveXML({ format: true });
  return xml;
}

// ── lint ──────────────────────────────────────────────────────────────────
function renderLint(l: Payload["lint"] | undefined) {
  const canvas = modeler.get("canvas");
  const overlays = modeler.get("overlays");
  const registry = modeler.get("elementRegistry");
  overlays.remove({ type: "lint" });
  for (const el of registry.getAll()) {
    canvas.removeMarker(el.id, "lint-error");
    canvas.removeMarker(el.id, "lint-warning");
  }
  const badge = $("lint-badge");
  const list = $("lint-list");
  list.replaceChildren();
  if (!l) {
    badge.textContent = "lint …";
    return;
  }
  const clean = l.errorCount + l.warningCount === 0 && !l.rulesetWarning;
  badge.textContent = clean ? "✓ lint clean" : `${l.errorCount} errors · ${l.warningCount} warnings`;
  badge.className = `pill ${clean ? "ok" : l.errorCount ? "bad" : "warn"}`;
  if (l.rulesetWarning) list.append(Object.assign(document.createElement("div"), { className: "issue warn", textContent: `⚠ ${l.rulesetWarning}` }));
  const byEl = new Map<string, LintIssue[]>();
  for (const i of l.issues) byEl.set(i.id, [...(byEl.get(i.id) ?? []), i]);
  for (const [id, issues] of byEl) {
    const isErr = issues.some((i) => i.category === "error");
    if (registry.get(id)) {
      canvas.addMarker(id, isErr ? "lint-error" : "lint-warning");
      overlays.add(id, "lint", {
        position: { top: -10, right: 10 },
        html: `<div class="lint-dot ${isErr ? "bad" : "warn"}" title="${issues.map((i) => i.message.replace(/"/g, "&quot;")).join("\n")}">${issues.length}</div>`,
      });
    }
    for (const i of issues) {
      const row = document.createElement("div");
      row.className = `issue ${i.category === "error" ? "bad" : "warn"}`;
      row.textContent = `${i.category === "error" ? "✗" : "⚠"} ${registry.get(id)?.businessObject?.name || id}: ${i.message}`;
      row.onclick = () => {
        const el = registry.get(id);
        if (el) {
          modeler.get("selection").select(el);
          canvas.scrollToElement?.(el);
        }
      };
      list.append(row);
    }
  }
}

async function relint() {
  try {
    const r = await app.callServerTool({ name: "ui_lint", arguments: { xml: await currentXml() } });
    if (doc) doc.lint = r.structuredContent as Payload["lint"];
    renderLint(doc?.lint);
  } catch (e) {
    console.warn("lint failed", e);
  }
}

// ── collaboration: keep the agent informed ────────────────────────────────
async function sync(save = false, note?: string) {
  if (!doc) return;
  const xml = await currentXml();
  const r = await app.callServerTool({ name: "ui_sync", arguments: { docId: doc.docId, xml, save, ...(note ? { note } : {}) } });
  if (r.isError) throw new Error(String((r.content?.[0] as any)?.text ?? "sync failed"));
  const l = doc.lint;
  const lintTxt = l ? `${l.errorCount} lint errors, ${l.warningCount} warnings` : "lint pending";
  await app
    .updateModelContext({
      content: [
        {
          type: "text",
          text:
            `The user has ${save ? "edited and SAVED" : "edited (not yet saved)"} the BPMN diagram "${doc.title}" (docId ${doc.docId}${doc.path ? `, file ${doc.path}` : ""}) in the BPMN Studio view; ${lintTxt}. ` +
            `Before changing this process further, call get_bpmn_edits with docId "${doc.docId}" to get their version${save ? "" : " (and save it to the file if appropriate)"}.`,
        },
      ],
    })
    .catch(() => {});
}
const syncSoon = debounce(() => sync().catch((e) => console.warn(e)), 1200);
const lintSoon = debounce(relint, 600);

async function shareWithClaude(text: string, asNote: boolean) {
  if (!doc) return;
  try {
    await sync(false, asNote ? text : undefined);
    if (asNote) {
      await app.updateModelContext({ content: [{ type: "text", text: `Latest test-studio run for "${doc.title}":\n${text}` }] });
      toast("Shared with Claude — it will see this on your next message");
    } else {
      const r = await app.sendMessage({ role: "user", content: [{ type: "text", text: `${text}\n\n(about BPMN "${doc.title}", docId ${doc.docId}${dirty ? " — I edited it in the view; use get_bpmn_edits" : ""})` }] });
      toast(r.isError ? "Host refused the message" : "Sent", !!r.isError);
    }
  } catch (e) {
    toast(String(e), true);
  }
}

modeler.on("commandStack.changed", () => {
  if (importing || tab === "test") return;
  dirty = true;
  $("dirty").classList.remove("hidden");
  lintSoon();
  syncSoon();
});

// ── loading ───────────────────────────────────────────────────────────────
async function load(p: Payload) {
  doc = p;
  dirty = false;
  $("dirty").classList.add("hidden");
  $("title").textContent = p.title;
  $("title").title = p.path ?? "";
  ($("btn-save") as HTMLButtonElement).disabled = !p.path;
  importing = true;
  try {
    const { warnings } = await modeler.importXML(p.xml);
    if (warnings?.length) console.warn("import warnings", warnings);
    modeler.get("canvas").zoom("fit-viewport", "auto");
  } catch (e) {
    toast(`Could not render diagram: ${e instanceof Error ? e.message : e}`, true);
  } finally {
    importing = false;
  }
  if (p.lint) renderLint(p.lint);
  else relint();
  await setTab(p.mode === "test" ? "test" : "model", p.scenario);
}

async function setTab(next: "model" | "test", scenario?: ScenarioPayload) {
  tab = next;
  document.querySelectorAll<HTMLButtonElement>(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === next));
  document.body.classList.toggle("testing", next === "test");
  $("studio").classList.toggle("hidden", next !== "test");
  $("props").classList.toggle("hidden", next === "test" || !showProps);
  $("side").classList.toggle("hidden", next === "model" && !showProps);
  requestAnimationFrame(() => {
    const canvas = modeler.get("canvas");
    canvas.resized();
    canvas.zoom("fit-viewport", "auto");
  });
  if (next === "test") {
    renderLint(undefined);
    $("lint-badge").textContent = "test mode";
    $("lint-badge").className = "pill";
    await studio.open(await currentXml(), scenario ?? null);
  } else {
    studio.close();
    relint();
  }
}

// ── toolbar ───────────────────────────────────────────────────────────────
document.querySelectorAll<HTMLButtonElement>(".tab").forEach((b) => (b.onclick = () => setTab(b.dataset.tab as "model" | "test")));
$("btn-fit").onclick = () => modeler.get("canvas").zoom("fit-viewport", "auto");
$("btn-props").onclick = () => {
  showProps = !showProps;
  if (tab === "model") {
    $("side").classList.toggle("hidden", !showProps);
    $("props").classList.toggle("hidden", !showProps);
  }
};
$("btn-save").onclick = async () => {
  try {
    await sync(true);
    dirty = false;
    $("dirty").classList.add("hidden");
    toast(`Saved ${doc?.path}`);
  } catch (e) {
    toast(String(e instanceof Error ? e.message : e), true);
  }
};
$("btn-full").onclick = async () => {
  const ctx = app.getHostContext();
  const mode = ctx?.displayMode === "fullscreen" ? "inline" : "fullscreen";
  if (ctx?.availableDisplayModes && !ctx.availableDisplayModes.includes(mode)) return toast("Host doesn't support fullscreen", true);
  await app.requestDisplayMode({ mode }).catch((e) => toast(String(e), true));
};
$("ask").onsubmit = (ev) => {
  ev.preventDefault();
  const input = $<HTMLInputElement>("ask-text");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  shareWithClaude(text, false);
};

// ── host wiring ───────────────────────────────────────────────────────────
function onContext(ctx: McpUiHostContext) {
  if (ctx.theme) {
    applyDocumentTheme(ctx.theme);
    document.body.dataset.theme = ctx.theme;
  }
  if (ctx.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
  if (ctx.styles?.css?.fonts) applyHostFonts(ctx.styles.css.fonts);
  if (ctx.displayMode) {
    document.body.dataset.mode = ctx.displayMode;
    $("btn-full").textContent = ctx.displayMode === "fullscreen" ? "⤡" : "⤢";
    requestAnimationFrame(() => modeler.get("canvas").resized());
  }
}

app.ontoolinput = () => {
  if (!doc) $("title").textContent = "Loading diagram…";
};
app.ontoolresult = (result) => {
  const p = result.structuredContent as unknown as Payload | undefined;
  const msg = String((result.content?.[0] as any)?.text ?? "Tool failed");
  if (!p?.xml) {
    $("title").textContent = "No diagram";
    toast(msg, true);
    return;
  }
  load(p);
  // e.g. test_bpmn refused by the lint gate: show the diagram with its lint markers, plus the reason.
  if (result.isError) toast(msg.split("\n")[0], true);
};
app.onhostcontextchanged = onContext;
app.onerror = console.error;
app.onteardown = async () => {
  if (dirty) await sync().catch(() => {});
  return {};
};

// Let the agent read the live diagram straight from the view (app-provided tools).
try {
  (app as any).registerTool?.(
    "studio_get_current_xml",
    { description: "Return the BPMN XML currently shown (including unsaved user edits) in the BPMN Studio view." },
    async () => ({ content: [{ type: "text", text: doc ? await currentXml() : "no diagram loaded" }] }),
  );
} catch (e) {
  console.warn("registerTool unsupported", e);
}

app.connect().then(() => {
  const ctx = app.getHostContext();
  if (ctx) onContext(ctx);
});
