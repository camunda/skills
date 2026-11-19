import { registerAppResource, registerAppTool, RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps/server";
import { McpServer, type CallToolResult, type ReadResourceResult } from "@modelcontextprotocol/server";
import fs from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { formatLint, lintBpmn } from "./lint.js";
import { runServerOp } from "./engine.js";
import { formatScenario, runScenario, ScenarioStep } from "./scenario.js";
import { describeSnapshot, type EngineOp } from "../shared/engine.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
/** The bundle's own directory when bundled (index.js + mcp-app.html side by side), repo/dist from source. */
const DIST_DIR = existsSync(path.join(HERE, "mcp-app.html")) ? HERE : path.resolve(HERE, "../../dist");
const ROOT = process.env.BPMN_MCP_ROOT ? path.resolve(process.env.BPMN_MCP_ROOT) : process.cwd();

export const RESOURCE_URI = "ui://bpmn/studio.html";

/** Documents the view has seen, keyed by docId. Shared across HTTP requests. */
interface Doc {
  docId: string;
  path?: string;
  xml: string;
  /** XML as last edited in the UI (undefined = no user edits). */
  draft?: string;
  draftAt?: string;
  savedAt?: string;
  /** Free-text notes pushed from the view (e.g. test run summaries). */
  notes: string[];
}
const docs = new Map<string, Doc>();

function resolvePath(p: string): string {
  return path.isAbsolute(p) ? p : path.resolve(ROOT, p);
}

/** Writes are limited to .bpmn files under BPMN_MCP_ROOT (default: the server's cwd). */
function writablePath(p: string): string {
  const abs = resolvePath(p);
  const rel = path.relative(ROOT, abs);
  if (rel.startsWith("..") || path.isAbsolute(rel)) throw new Error(`Refusing to write outside ${ROOT} (set BPMN_MCP_ROOT to change): ${abs}`);
  if (!abs.endsWith(".bpmn")) throw new Error(`Only .bpmn files can be written: ${abs}`);
  return abs;
}

function docIdFor(p?: string) {
  return p ? "file:" + createHash("sha256").update(p).digest("hex").slice(0, 16) : "mem:" + randomUUID().slice(0, 8);
}

async function loadSource(args: { path?: string; xml?: string; docId?: string }): Promise<{ xml: string; path?: string; doc?: Doc }> {
  if (args.docId && docs.has(args.docId)) {
    const d = docs.get(args.docId)!;
    return { xml: d.draft ?? d.xml, path: d.path, doc: d };
  }
  if (args.xml) return { xml: args.xml, path: args.path ? resolvePath(args.path) : undefined };
  if (args.path) {
    const abs = resolvePath(args.path);
    return { xml: await fs.readFile(abs, "utf8"), path: abs };
  }
  throw new Error("Provide `path` (a .bpmn file) or `xml`.");
}

const text = (t: string, structuredContent?: Record<string, unknown>, isError = false): CallToolResult => ({
  content: [{ type: "text", text: t }],
  ...(structuredContent ? { structuredContent } : {}),
  ...(isError ? { isError: true } : {}),
});

const srcShape = {
  path: z.string().optional().describe("Path to a .bpmn file (absolute, or relative to the server root). With `xml`, the target file the view's Save button writes to."),
  xml: z.string().optional().describe("BPMN XML, if not reading from a file"),
};

export function createServer(): McpServer {
  const server = new McpServer({ name: "bpmn-studio", version: "0.1.0" });
  const ui = { resourceUri: RESOURCE_URI };

  // ── Model-facing tools ──────────────────────────────────────────────────
  registerAppTool(
    server,
    "show_bpmn",
    {
      title: "Show BPMN diagram",
      description:
        "Render a BPMN process interactively for the user (bpmn-js) with lint markers. The user can inspect, edit, save and test-run it in the view. " +
        "Call this after creating or changing a .bpmn file. Afterwards, call get_bpmn_edits to pick up anything the user changed.",
      inputSchema: { ...srcShape, title: z.string().optional() },
      _meta: { ui },
    },
    async (args): Promise<CallToolResult> => {
      try {
        const src = await loadSource(args);
        const docId = docIdFor(src.path);
        const prev = docs.get(docId);
        docs.set(docId, { docId, path: src.path, xml: src.xml, notes: prev?.notes ?? [] });
        const lint = await lintBpmn(src.xml);
        return text(
          `Showing ${src.path ?? "inline diagram"} (docId ${docId}) to the user.\n${formatLint(lint)}`,
          { docId, path: src.path ?? null, title: args.title ?? (src.path ? path.basename(src.path) : "BPMN"), xml: src.xml, lint, mode: "edit" },
        );
      } catch (e) {
        return text(String(e instanceof Error ? e.message : e), undefined, true);
      }
    },
  );

  server.registerTool(
    "lint_bpmn",
    {
      title: "Lint BPMN",
      description:
        "Lint a BPMN file/XML with @camunda/linting (the Camunda Modeler / c8ctl rule engine incl. camunda-compat for the declared executionPlatformVersion). Returns errors and warnings with element ids.",
      inputSchema: srcShape,
    },
    async (args): Promise<CallToolResult> => {
      try {
        const { xml } = await loadSource(args);
        const r = await lintBpmn(xml);
        return text(formatLint(r), r as unknown as Record<string, unknown>);
      } catch (e) {
        return text(String(e instanceof Error ? e.message : e), undefined, true);
      }
    },
  );

  registerAppTool(
    server,
    "test_bpmn",
    {
      title: "Test-run BPMN",
      description:
        "Execute a BPMN process in the embedded nanobpmn engine (WASM) with a scripted scenario and assertions, then show the run in the test studio. " +
        "Steps: start{processId?,variables?}, completeJob{jobType?|elementId?,variables?}, throwError{jobType?|elementId?,errorCode}, failJob, completeUserTask{elementId?,variables?}, " +
        "message{name,correlationKey?,variables?}, signal{name}, advanceTime{ms}, expect{completed?,active?,passed?,notPassed?,variables?,noIncidents?}. " +
        "Use it to prove each gateway branch behaves as intended. " +
        "The diagram is linted first (same rules as lint_bpmn); if it has lint errors the scenario is NOT run — fix them and call again. Warnings don't block.",
      inputSchema: { ...srcShape, docId: z.string().optional(), steps: z.array(ScenarioStep).min(1) },
      _meta: { ui },
    },
    async (args): Promise<CallToolResult> => {
      try {
        const src = await loadSource(args);
        const docId = src.doc?.docId ?? docIdFor(src.path);
        if (!docs.has(docId)) docs.set(docId, { docId, path: src.path, xml: src.xml, notes: [] });
        const lint = await lintBpmn(src.xml);
        if (lint.parseError || lint.errorCount > 0) {
          // Lint gate: don't run invalid models. Still open the view (model tab) so the user sees the markers.
          return text(
            `Not run: the diagram has lint errors. Fix them, then call test_bpmn again.\n${formatLint(lint)}`,
            { docId, path: src.path ?? null, title: src.path ? path.basename(src.path) : "BPMN test run", xml: src.xml, mode: "model" },
            true,
          );
        }
        const r = runScenario(src.xml, args.steps);
        return text(`${formatScenario(r)}\n${formatLint(lint)}`, {
          docId,
          path: src.path ?? null,
          title: src.path ? path.basename(src.path) : "BPMN test run",
          xml: src.xml,
          mode: "test",
          scenario: { passed: r.passed, outcomes: r.outcomes, ops: r.ops.slice(1) },
        });
      } catch (e) {
        return text(String(e instanceof Error ? e.message : e), undefined, true);
      }
    },
  );

  server.registerTool(
    "get_bpmn_edits",
    {
      title: "Get user edits",
      description:
        "Fetch the user's edits and notes from the BPMN view (they may have changed the diagram, saved it, or test-run it). Call this when the user says they changed the diagram, before making further edits to a file you showed.",
      inputSchema: { docId: z.string().optional(), path: z.string().optional() },
    },
    async ({ docId, path: p }): Promise<CallToolResult> => {
      const id = docId ?? (p ? docIdFor(resolvePath(p)) : undefined);
      const list = id ? [docs.get(id)].filter(Boolean) as Doc[] : [...docs.values()];
      if (!list.length) return text("No diagram is open in the view.");
      const parts = list.map((d) => {
        const head = `docId ${d.docId}${d.path ? ` (${d.path})` : ""}: ` + (d.draft ? `user-edited at ${d.draftAt}${d.savedAt ? `, saved to disk at ${d.savedAt}` : ", NOT saved to disk"}` : "no user edits");
        const notes = d.notes.length ? `\nnotes from the view:\n${d.notes.slice(-5).join("\n")}` : "";
        return head + notes + (d.draft ? `\n\n${d.draft}` : "");
      });
      return text(parts.join("\n\n---\n\n"));
    },
  );

  server.registerTool(
    "save_bpmn",
    {
      title: "Save BPMN",
      description:
        `Write BPMN XML to a .bpmn file under ${ROOT}. Use this in clients without their own file access (e.g. Claude Desktop). ` +
        "Pass `docId` to save the diagram as currently shown in the view (including the user's edits), or `xml`.",
      inputSchema: { path: z.string(), xml: z.string().optional(), docId: z.string().optional() },
    },
    async ({ path: p, xml, docId }): Promise<CallToolResult> => {
      try {
        const abs = writablePath(p);
        const d = docId ? docs.get(docId) : undefined;
        const body = xml ?? d?.draft ?? d?.xml;
        if (!body) throw new Error("Nothing to save: pass xml or a known docId.");
        await fs.mkdir(path.dirname(abs), { recursive: true });
        await fs.writeFile(abs, body, "utf8");
        if (d) Object.assign(d, { path: abs, xml: body, draft: undefined, savedAt: new Date().toISOString() });
        const lint = await lintBpmn(body);
        return text(`saved ${abs}\n${formatLint(lint)}`, { path: abs });
      } catch (e) {
        return text(String(e instanceof Error ? e.message : e), undefined, true);
      }
    },
  );

  // ── App-only tools (called by the view, hidden from the model) ──────────
  const appOnly = { ui: { resourceUri: RESOURCE_URI, visibility: ["app"] as const } };

  registerAppTool(
    server,
    "ui_lint",
    { description: "Lint XML for the view.", inputSchema: { xml: z.string() }, _meta: appOnly as any },
    async ({ xml }): Promise<CallToolResult> => {
      const r = await lintBpmn(xml);
      return text(formatLint(r), r as unknown as Record<string, unknown>);
    },
  );

  registerAppTool(
    server,
    "ui_sync",
    {
      description: "Record the view's current XML as the user's draft; optionally save it back to the document's file.",
      inputSchema: { docId: z.string(), xml: z.string(), save: z.boolean().optional(), note: z.string().optional() },
      _meta: appOnly as any,
    },
    async ({ docId, xml, save, note }): Promise<CallToolResult> => {
      const d = docs.get(docId) ?? { docId, xml, notes: [] };
      docs.set(docId, d);
      if (note) d.notes.push(`[${new Date().toISOString()}] ${note}`);
      if (xml && xml !== d.xml) {
        d.draft = xml;
        d.draftAt = new Date().toISOString();
      }
      if (save) {
        if (!d.path) return text("This diagram has no file path; cannot save.", { saved: false }, true);
        try {
          writablePath(d.path);
        } catch (e) {
          return text(String(e instanceof Error ? e.message : e), { saved: false }, true);
        }
        await fs.mkdir(path.dirname(d.path), { recursive: true });
        await fs.writeFile(d.path, xml, "utf8");
        d.xml = xml;
        d.savedAt = new Date().toISOString();
      }
      return text(save ? `saved ${d.path}` : "synced", { saved: !!save, path: d.path ?? null });
    },
  );

  registerAppTool(
    server,
    "ui_engine",
    {
      description: "Server-side engine fallback for the test studio (used when WASM can't run in the iframe).",
      inputSchema: { sessionId: z.string().optional(), cmd: z.record(z.string(), z.unknown()) },
      _meta: appOnly as any,
    },
    async ({ sessionId, cmd }): Promise<CallToolResult> => {
      const r = runServerOp(sessionId, cmd as unknown as EngineOp);
      return text(r.ok ? describeSnapshot(r.snapshot) : `error: ${r.error}`, r as unknown as Record<string, unknown>);
    },
  );

  // ── The view ────────────────────────────────────────────────────────────
  registerAppResource(server, "BPMN Studio", RESOURCE_URI, { mimeType: RESOURCE_MIME_TYPE }, async (): Promise<ReadResourceResult> => {
    const html = await fs.readFile(path.join(DIST_DIR, "mcp-app.html"), "utf8");
    return {
      contents: [
        {
          uri: RESOURCE_URI,
          mimeType: RESOURCE_MIME_TYPE,
          text: html,
          _meta: { ui: { prefersBorder: true, ...(process.env.BPMN_MCP_UI_DOMAIN ? { domain: process.env.BPMN_MCP_UI_DOMAIN } : {}) } },
        },
      ],
    };
  });

  return server;
}
