import type { App } from "@modelcontextprotocol/ext-apps";
import { applyOp, type EngineOp, type EngineResult } from "../shared/engine";

export interface EngineClient {
  kind: "wasm" | "server";
  /** why we're on the server fallback, if we are */
  reason?: string;
  run(cmd: EngineOp): Promise<EngineResult>;
}

/**
 * Prefer the engine compiled to WASM running *inside the view* (no round-trips,
 * works offline). If the host's CSP forbids WebAssembly compilation (no
 * 'wasm-unsafe-eval'), fall back to the same engine running in the MCP server,
 * reached through the app-only `ui_engine` tool.
 */
export async function createEngine(app: App): Promise<EngineClient> {
  try {
    const [{ initSync, TestEngine }, { default: b64 }] = await Promise.all([import("@nanobpm/engine-wasm"), import("virtual:engine-wasm")]);
    const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    initSync({ module: bin });
    const engine = new TestEngine();
    // tiny self-test so a half-working module doesn't masquerade as OK
    JSON.parse(engine.snapshot());
    return { kind: "wasm", run: async (cmd) => applyOp(engine as any, cmd) };
  } catch (e) {
    const reason = e instanceof Error ? e.message : String(e);
    console.warn("[bpmn-studio] WASM engine unavailable in view, using server engine:", reason);
    let sessionId: string | undefined;
    return {
      kind: "server",
      reason,
      async run(cmd) {
        const r = await app.callServerTool({ name: "ui_engine", arguments: { sessionId, cmd } });
        const sc = (r.structuredContent ?? {}) as EngineResult & { sessionId?: string };
        sessionId = sc.sessionId ?? sessionId;
        if (r.isError && !sc.snapshot) return { ok: false, error: String((r.content?.[0] as any)?.text ?? "engine error"), snapshot: null };
        return sc;
      },
    };
  }
}
