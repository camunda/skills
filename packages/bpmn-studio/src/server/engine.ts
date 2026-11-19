import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { randomUUID } from "node:crypto";
// The read-model build: same engine plus the C8-style read channel, which is what keeps a
// completed instance's final variables readable (see withFinalVariables in ../shared/engine).
import { initSync, TestEngine } from "@nanobpm/engine-wasm/readmodel";
import { applyOp, type EngineOp, type EngineResult } from "../shared/engine.js";

let initialised = false;
function ensureInit() {
  if (initialised) return;
  // dist/ ships its own copy (self-contained plugin installs); fall back to node_modules when run from source.
  let wasmPath = path.join(path.dirname(fileURLToPath(import.meta.url)), "nanobpmn_engine_bg.wasm");
  if (!fs.existsSync(wasmPath)) wasmPath = createRequire(import.meta.url).resolve("@nanobpm/engine-wasm/readmodel/nanobpmn_engine_bg.wasm");
  initSync({ module: fs.readFileSync(wasmPath) });
  initialised = true;
}

interface Session {
  engine: TestEngine;
  touched: number;
}

const sessions = new Map<string, Session>();
const MAX_SESSIONS = 20;

function gc() {
  if (sessions.size <= MAX_SESSIONS) return;
  const oldest = [...sessions.entries()].sort((a, b) => a[1].touched - b[1].touched)[0];
  if (oldest) {
    oldest[1].engine.free();
    sessions.delete(oldest[0]);
  }
}

/** Run one op against a server-side engine session (creating it on demand). */
export function runServerOp(sessionId: string | undefined, cmd: EngineOp): EngineResult & { sessionId: string } {
  ensureInit();
  const id = sessionId || randomUUID();
  let s = sessions.get(id);
  if (!s) {
    s = { engine: new TestEngine(), touched: Date.now() };
    sessions.set(id, s);
    gc();
  }
  s.touched = Date.now();
  return { ...applyOp(s.engine as any, cmd), sessionId: id };
}

/** One-shot headless engine for scripted scenarios. */
export function withFreshEngine<T>(fn: (e: TestEngine) => T): T {
  ensureInit();
  const e = new TestEngine();
  try {
    return fn(e);
  } finally {
    e.free();
  }
}
