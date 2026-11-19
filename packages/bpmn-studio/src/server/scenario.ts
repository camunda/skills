import { z } from "zod";
import { applyOp, describeSnapshot, type EngineOp, type Snapshot } from "../shared/engine.js";
import { withFreshEngine } from "./engine.js";

const vars = z.record(z.string(), z.unknown()).optional();

export const ScenarioStep = z.discriminatedUnion("action", [
  z.object({ action: z.literal("start"), processId: z.string().optional(), variables: vars }),
  z.object({
    action: z.literal("completeJob"),
    jobType: z.string().optional().describe("zeebe:taskDefinition type"),
    elementId: z.string().optional(),
    variables: vars,
  }),
  z.object({
    action: z.literal("throwError"),
    jobType: z.string().optional(),
    elementId: z.string().optional(),
    errorCode: z.string(),
    message: z.string().optional(),
  }),
  z.object({ action: z.literal("failJob"), jobType: z.string().optional(), elementId: z.string().optional(), message: z.string().optional() }),
  z.object({ action: z.literal("completeUserTask"), elementId: z.string().optional(), variables: vars }),
  z.object({ action: z.literal("message"), name: z.string(), correlationKey: z.string().optional(), variables: vars }),
  z.object({ action: z.literal("signal"), name: z.string(), variables: vars }),
  z.object({ action: z.literal("advanceTime"), ms: z.number() }),
  z.object({
    action: z.literal("expect"),
    completed: z.boolean().optional().describe("the instance has completed"),
    active: z.array(z.string()).optional().describe("element ids that must be active (waiting)"),
    passed: z.array(z.string()).optional().describe("element ids that must have been entered at least once"),
    notPassed: z.array(z.string()).optional(),
    variables: vars.describe("subset of instance variables that must match (JSON equality)"),
    noIncidents: z.boolean().optional(),
  }),
]);
export type ScenarioStep = z.infer<typeof ScenarioStep>;

export interface StepOutcome {
  index: number;
  step: ScenarioStep;
  ok: boolean;
  detail: string;
}

export interface ScenarioResult {
  passed: boolean;
  processIds: string[];
  outcomes: StepOutcome[];
  snapshot: Snapshot | null;
  /** ops actually applied — lets the view replay the run in its own engine */
  ops: EngineOp[];
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function visited(s: Snapshot): Set<string> {
  const v = new Set<string>();
  for (const f of s.takenSequenceFlows ?? []) {
    v.add(f.from);
    v.add(f.to);
  }
  for (const e of s.elementStats ?? []) if (e.active + e.completed + e.incidents > 0) v.add(e.elementId);
  for (const a of s.activeElementIds ?? []) v.add(a);
  return v;
}

export function runScenario(xml: string, steps: ScenarioStep[]): ScenarioResult {
  return withFreshEngine((engine) => {
    const ops: EngineOp[] = [];
    const outcomes: StepOutcome[] = [];
    const deployed = applyOp(engine as any, { op: "deploy", xml });
    if (!deployed.ok) {
      return { passed: false, processIds: [], outcomes: [{ index: -1, step: { action: "start" }, ok: false, detail: `deploy failed: ${deployed.error}` }], snapshot: null, ops };
    }
    ops.push({ op: "deploy", xml: "" });
    const processIds = deployed.processIds ?? [];
    let snap: Snapshot | null = deployed.snapshot;
    let instanceKey = "";

    const run = (op: EngineOp) => {
      const r = applyOp(engine as any, op);
      ops.push(op);
      if (r.snapshot) snap = r.snapshot;
      return r;
    };
    const findJob = (st: { jobType?: string; elementId?: string }) =>
      (snap?.jobs ?? []).find(
        (j) => (!st.jobType || j.jobType === st.jobType) && (!st.elementId || j.elementId === st.elementId) && /created|activated/i.test(String(j.state)),
      );

    steps.forEach((step, index) => {
      const out = (ok: boolean, detail: string) => outcomes.push({ index, step, ok, detail });
      switch (step.action) {
        case "start": {
          const pid = step.processId ?? processIds[0];
          const r = run({ op: "createInstance", processId: pid, variables: step.variables });
          if (r.ok) instanceKey = r.created ?? instanceKey;
          return out(r.ok, r.ok ? `started ${pid} → instance ${r.created}` : r.error!);
        }
        case "completeJob":
        case "throwError":
        case "failJob": {
          const job = findJob(step);
          if (!job) return out(false, `no open job matching ${JSON.stringify({ jobType: step.jobType, elementId: step.elementId })}`);
          const r =
            step.action === "completeJob"
              ? run({ op: "completeJob", jobKey: String(job.key), variables: step.variables })
              : step.action === "throwError"
                ? run({ op: "throwError", jobKey: String(job.key), errorCode: step.errorCode, message: step.message })
                : run({ op: "failJob", jobKey: String(job.key), retries: 0, message: step.message });
          return out(r.ok, r.ok ? `${step.action} ${job.jobType}@${job.elementId}` : r.error!);
        }
        case "completeUserTask": {
          const t = (snap?.userTasks ?? []).find((u) => (!step.elementId || u.elementId === step.elementId) && /created|assigned/i.test(String(u.state)));
          if (!t) return out(false, `no open user task${step.elementId ? ` at ${step.elementId}` : ""}`);
          const r = run({ op: "completeUserTask", userTaskKey: String(t.key), variables: step.variables });
          return out(r.ok, r.ok ? `completed user task ${t.elementId}` : r.error!);
        }
        case "message": {
          const r = run({ op: "correlateMessage", name: step.name, correlationKey: step.correlationKey, variables: step.variables });
          return out(r.ok, r.ok ? `published message ${step.name}` : r.error!);
        }
        case "signal": {
          const r = run({ op: "broadcastSignal", name: step.name, variables: step.variables });
          return out(r.ok, r.ok ? `broadcast signal ${step.name}` : r.error!);
        }
        case "advanceTime": {
          const r = run({ op: "advanceTime", ms: step.ms });
          return out(r.ok, r.ok ? `advanced clock ${step.ms}ms` : r.error!);
        }
        case "expect": {
          const s = snap;
          if (!s) return out(false, "no engine state");
          const inst = s.instances.find((i) => i.key === instanceKey) ?? s.instances[s.instances.length - 1];
          const fails: string[] = [];
          if (step.completed !== undefined && !!inst?.completed !== step.completed) fails.push(`expected completed=${step.completed}, state=${inst?.state}`);
          for (const a of step.active ?? []) if (!s.activeElementIds.includes(a)) fails.push(`expected ${a} active (active: ${s.activeElementIds.join(",") || "none"})`);
          const v = visited(s);
          for (const p of step.passed ?? []) if (!v.has(p)) fails.push(`expected path through ${p}`);
          for (const p of step.notPassed ?? []) if (v.has(p)) fails.push(`expected NOT to pass ${p}`);
          for (const [k, val] of Object.entries(step.variables ?? {}))
            if (inst?.truncatedVariables?.includes(k)) fails.push(`variable ${k}: final value is too large for the read model to return in full, so it cannot be asserted`);
            else if (!same(inst?.variables?.[k], val)) fails.push(`variable ${k}: expected ${JSON.stringify(val)}, got ${JSON.stringify(inst?.variables?.[k])}`);
          if (step.noIncidents && s.incidents.length) fails.push(`incidents: ${JSON.stringify(s.incidents)}`);
          return out(fails.length === 0, fails.length ? fails.join("; ") : "expectations met");
        }
      }
    });
    // ops[0] is a placeholder deploy; callers re-insert the xml.
    return { passed: outcomes.every((o) => o.ok), processIds, outcomes, snapshot: snap, ops };
  });
}

export function formatScenario(r: ScenarioResult): string {
  const lines = r.outcomes.map((o) => `${o.ok ? "✓" : "✗"} ${o.index + 1}. ${o.step.action}: ${o.detail}`);
  return [`scenario ${r.passed ? "PASSED" : "FAILED"} (processes: ${r.processIds.join(", ")})`, ...lines, "", "final state:", describeSnapshot(r.snapshot)].join("\n");
}
