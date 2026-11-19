/**
 * Engine-agnostic test-run driver shared by the in-browser studio (WASM in the
 * iframe) and the server-side fallback (WASM in Node). Both sides speak the same
 * `EngineOp` vocabulary, so the view can switch transport transparently.
 */

/** The subset of `@nanobpm/engine-wasm`'s `TestEngine` we drive. */
export interface TestEngineLike {
  deploy(xml: string): string;
  createInstance(processId: string, variablesJson: string, version?: number | null): string;
  snapshot(): string;
  events(): string;
  activateJobs(type: string, max: number, timeoutMs: number, worker: string, withLease?: boolean | null): string;
  completeJob(jobKey: string, variablesJson: string, leaseToken?: string | null): string;
  failJob(jobKey: string, retries: number, errorMessage: string, ...rest: unknown[]): string;
  throwError(jobKey: string, errorCode: string, errorMessage: string, ...rest: unknown[]): string;
  completeUserTask(userTaskKey: string, variablesJson: string): string;
  correlateMessage(name: string, correlationKey: string, variablesJson: string): string;
  broadcastSignal(name: string, variablesJson: string): string;
  advanceTime(byMs: number): string;
  cancelInstance(instanceKey: string): string;
  reset(): void;
  /** Read-model engines only (`@nanobpm/engine-wasm/readmodel`): the C8-style variables search. */
  searchVariables?(filterJson: string): string;
}

export type EngineOp =
  | { op: "deploy"; xml: string }
  | { op: "createInstance"; processId: string; variables?: Record<string, unknown> }
  | { op: "completeJob"; jobKey: string; variables?: Record<string, unknown> }
  | { op: "failJob"; jobKey: string; retries?: number; message?: string }
  | { op: "throwError"; jobKey: string; errorCode: string; message?: string }
  | { op: "completeUserTask"; userTaskKey: string; variables?: Record<string, unknown> }
  | { op: "correlateMessage"; name: string; correlationKey?: string; variables?: Record<string, unknown> }
  | { op: "broadcastSignal"; name: string; variables?: Record<string, unknown> }
  | { op: "advanceTime"; ms: number }
  | { op: "cancelInstance"; instanceKey: string }
  | { op: "snapshot" }
  | { op: "reset" };

export interface Snapshot {
  activeElementIds: string[];
  incidentElementIds: string[];
  takenSequenceFlows: { from: string; to: string }[];
  elementStats: { elementId: string; active: number; completed: number; incidents: number }[];
  instances: {
    key: string;
    processId: string;
    state: string;
    completed: boolean;
    /** Root-scope variables. For a finished instance these are its final variables (see `withFinalVariables`). */
    variables: Record<string, unknown>;
    /** Final variables the read model could not return in full (values over its preview limit). */
    truncatedVariables?: string[];
    activeElements: unknown[];
  }[];
  jobs: Array<Record<string, any>>;
  userTasks: Array<Record<string, any>>;
  incidents: Array<Record<string, any>>;
  timers: Array<Record<string, any>>;
  messageSubscriptions: Array<Record<string, any>>;
  signalSubscriptions: Array<Record<string, any>>;
  now: number;
  [k: string]: unknown;
}

export interface EngineResult {
  ok: boolean;
  error?: string;
  processIds?: string[];
  created?: string;
  snapshot: Snapshot | null;
}

const j = (v?: Record<string, unknown>) => JSON.stringify(v ?? {});

interface VariableItem {
  name: string;
  value: string;
  scopeKey: string;
  processInstanceKey: string;
  isTruncated?: boolean;
}

/**
 * The engine drops a process instance's variables from its live state the moment the
 * instance completes (Zeebe does the same: the variable scope is removed with the
 * instance; results are read from the export/read side). To keep a finished run
 * assertable, fill each finished instance's `variables` from the read model's variable
 * search when the engine offers one (the `readmodel` wasm build).
 *
 * Only variables whose scope IS the instance (root scope) count: sub-process / task /
 * multi-instance local variables live in their own scopes and are not instance variables,
 * exactly as while the instance is running. Values arrive JSON-encoded; ones over the
 * read model's preview limit arrive truncated and are reported in `truncatedVariables`
 * instead of being guessed at.
 */
function withFinalVariables(snap: Snapshot, engine: TestEngineLike): Snapshot {
  if (typeof engine.searchVariables !== "function") return snap;
  const finished = (snap.instances ?? []).filter((i) => i.completed && Object.keys(i.variables ?? {}).length === 0);
  if (finished.length === 0) return snap;
  const items: VariableItem[] = JSON.parse(engine.searchVariables("{}")).items ?? [];
  for (const inst of finished) {
    const vars: Record<string, unknown> = {};
    const truncated: string[] = [];
    for (const v of items) {
      if (v.processInstanceKey !== inst.key || v.scopeKey !== inst.key) continue;
      try {
        if (v.isTruncated) throw new Error("truncated");
        vars[v.name] = JSON.parse(v.value);
      } catch {
        truncated.push(v.name);
      }
    }
    inst.variables = vars;
    if (truncated.length) inst.truncatedVariables = truncated;
  }
  return snap;
}

/** Pull the snapshot out of whatever shape a TestEngine method returned. */
function asSnapshot(raw: string | undefined, engine: TestEngineLike): Snapshot {
  if (raw) {
    try {
      const v = JSON.parse(raw);
      if (v && typeof v === "object") {
        if (Array.isArray(v.activeElementIds)) return withFinalVariables(v as Snapshot, engine);
        if (v.snapshot && Array.isArray(v.snapshot.activeElementIds)) return withFinalVariables(v.snapshot as Snapshot, engine);
      }
    } catch {
      /* fall through */
    }
  }
  return withFinalVariables(JSON.parse(engine.snapshot()) as Snapshot, engine);
}

/** Apply one op to an engine. Never throws: engine errors come back as `{ok:false}`. */
export function applyOp(engine: TestEngineLike, cmd: EngineOp): EngineResult {
  try {
    switch (cmd.op) {
      case "deploy": {
        engine.reset();
        const r = JSON.parse(engine.deploy(cmd.xml));
        return { ok: true, processIds: r.processIds ?? [], snapshot: asSnapshot(undefined, engine) };
      }
      case "createInstance": {
        const raw = engine.createInstance(cmd.processId, j(cmd.variables));
        const snap = asSnapshot(raw, engine);
        return { ok: true, created: String((JSON.parse(raw) as any).created ?? ""), snapshot: snap };
      }
      case "completeJob":
        return { ok: true, snapshot: asSnapshot(engine.completeJob(cmd.jobKey, j(cmd.variables)), engine) };
      case "failJob":
        return { ok: true, snapshot: asSnapshot(engine.failJob(cmd.jobKey, cmd.retries ?? 0, cmd.message ?? "failed from test studio"), engine) };
      case "throwError":
        return { ok: true, snapshot: asSnapshot(engine.throwError(cmd.jobKey, cmd.errorCode, cmd.message ?? ""), engine) };
      case "completeUserTask":
        return { ok: true, snapshot: asSnapshot(engine.completeUserTask(cmd.userTaskKey, j(cmd.variables)), engine) };
      case "correlateMessage":
        return { ok: true, snapshot: asSnapshot(engine.correlateMessage(cmd.name, cmd.correlationKey ?? "", j(cmd.variables)), engine) };
      case "broadcastSignal":
        return { ok: true, snapshot: asSnapshot(engine.broadcastSignal(cmd.name, j(cmd.variables)), engine) };
      case "advanceTime":
        return { ok: true, snapshot: asSnapshot(engine.advanceTime(cmd.ms), engine) };
      case "cancelInstance":
        return { ok: true, snapshot: asSnapshot(engine.cancelInstance(cmd.instanceKey), engine) };
      case "reset":
        engine.reset();
        return { ok: true, snapshot: null };
      case "snapshot":
        return { ok: true, snapshot: asSnapshot(undefined, engine) };
    }
  } catch (e) {
    let snapshot: Snapshot | null = null;
    try {
      snapshot = asSnapshot(undefined, engine);
    } catch {
      /* engine may be unusable */
    }
    return { ok: false, error: e instanceof Error ? e.message : String(e), snapshot };
  }
}

/** Short human/agent-readable summary of a snapshot. */
export function describeSnapshot(s: Snapshot | null): string {
  if (!s) return "(no state)";
  const lines: string[] = [];
  for (const i of s.instances ?? []) lines.push(`instance ${i.key} (${i.processId}): ${i.state} vars=${JSON.stringify(i.variables)}`);
  if (s.activeElementIds?.length) lines.push(`active: ${s.activeElementIds.join(", ")}`);
  const openJobs = (s.jobs ?? []).filter((x) => !/complet|cancel/i.test(String(x.state ?? "")));
  if (openJobs.length) lines.push(`open jobs: ${openJobs.map((x) => `${x.key}[${x.jobType ?? x.type}@${x.elementId}]`).join(", ")}`);
  const openTasks = (s.userTasks ?? []).filter((x) => !/complet|cancel/i.test(String(x.state ?? "")));
  if (openTasks.length) lines.push(`open user tasks: ${openTasks.map((x) => `${x.key ?? x.userTaskKey}[${x.elementId}]`).join(", ")}`);
  if (s.messageSubscriptions?.length) lines.push(`waiting messages: ${s.messageSubscriptions.map((m) => `${m.messageName ?? m.name}(${m.correlationKey ?? ""})`).join(", ")}`);
  if (s.timers?.length) lines.push(`timers: ${s.timers.length}`);
  if (s.incidents?.length) lines.push(`INCIDENTS: ${s.incidents.map((x) => `${x.elementId}: ${x.errorMessage ?? x.message ?? JSON.stringify(x)}`).join("; ")}`);
  return lines.join("\n") || "(idle)";
}
