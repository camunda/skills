import type { EngineClient } from "./engine-client";
import type { EngineOp, EngineResult, Snapshot } from "../shared/engine";

interface Outcome {
  index: number;
  ok: boolean;
  detail: string;
  step: { action: string };
}
export interface ScenarioPayload {
  passed: boolean;
  outcomes: Outcome[];
  ops: EngineOp[];
}

const h = (tag: string, attrs: Record<string, any> = {}, ...kids: (Node | string | null | undefined | false)[]) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v !== undefined && v !== null && v !== false) el.setAttribute(k, String(v));
  }
  for (const k of kids) if (k) el.append(k);
  return el;
};

const parseVars = (s: string): Record<string, unknown> => {
  const t = s.trim();
  if (!t) return {};
  const v = JSON.parse(t);
  if (typeof v !== "object" || Array.isArray(v) || v === null) throw new Error("variables must be a JSON object");
  return v;
};

/**
 * The Nano-style test studio: drive the engine by hand (start, complete jobs and
 * user tasks, publish messages, advance the clock) and watch tokens on the canvas.
 */
export class Studio {
  private snap: Snapshot | null = null;
  private processIds: string[] = [];
  private log: string[] = [];
  private scenario: ScenarioPayload | null = null;
  private xml = "";
  private busy = false;

  constructor(
    private root: HTMLElement,
    private modeler: any,
    private getEngine: () => Promise<EngineClient>,
    private onReport: (summary: string) => void,
  ) {}

  async open(xml: string, scenario?: ScenarioPayload | null) {
    this.xml = xml;
    this.scenario = scenario ?? null;
    this.log = [];
    const r = await this.exec({ op: "deploy", xml }, false);
    this.processIds = r?.processIds ?? [];
    if (!r?.ok) this.note(`✗ deploy failed: ${r?.error}`);
    else this.note(`deployed ${this.processIds.join(", ")}`);
    if (this.scenario && r?.ok) {
      for (const op of this.scenario.ops) {
        const res = await this.exec(op, false);
        if (res && !res.ok) this.note(`✗ replay ${op.op}: ${res.error}`);
      }
      this.note(`replayed agent scenario (${this.scenario.ops.length} ops)`);
    }
    this.render();
  }

  close() {
    this.paint(null);
  }

  private note(s: string) {
    this.log.push(s);
    if (this.log.length > 60) this.log.shift();
  }

  private async exec(cmd: EngineOp, rerender = true): Promise<EngineResult | null> {
    if (this.busy) return null;
    this.busy = true;
    try {
      const engine = await this.getEngine();
      const r = await engine.run(cmd);
      if (r.snapshot) this.snap = r.snapshot;
      if (cmd.op !== "deploy" && cmd.op !== "snapshot") this.note(r.ok ? `✓ ${label(cmd)}` : `✗ ${label(cmd)}: ${r.error}`);
      this.paint(this.snap);
      return r;
    } catch (e) {
      this.note(`✗ ${cmd.op}: ${e instanceof Error ? e.message : e}`);
      return null;
    } finally {
      this.busy = false;
      if (rerender) this.render();
    }
  }

  private guard(fn: () => Promise<unknown>) {
    return async (ev?: Event) => {
      ev?.preventDefault();
      try {
        await fn();
      } catch (e) {
        this.note(`✗ ${e instanceof Error ? e.message : e}`);
        this.render();
      }
    };
  }

  /** Token markers + counts on the canvas. */
  paint(s: Snapshot | null) {
    const canvas = this.modeler.get("canvas");
    const registry = this.modeler.get("elementRegistry");
    const overlays = this.modeler.get("overlays");
    overlays.remove({ type: "tok" });
    for (const el of registry.getAll()) for (const m of ["tok-active", "tok-done", "tok-incident", "flow-taken"]) canvas.removeMarker(el.id, m);
    if (!s) return;
    const has = (id: string) => !!registry.get(id);
    for (const st of s.elementStats ?? []) {
      if (!has(st.elementId)) continue;
      if (st.completed > 0) canvas.addMarker(st.elementId, "tok-done");
      if (st.active > 0) {
        canvas.addMarker(st.elementId, "tok-active");
        overlays.add(st.elementId, "tok", { position: { bottom: 12, left: -10 }, html: `<div class="tok-badge">${st.active}</div>` });
      }
    }
    for (const id of s.activeElementIds ?? []) if (has(id)) canvas.addMarker(id, "tok-active");
    for (const id of s.incidentElementIds ?? []) if (has(id)) canvas.addMarker(id, "tok-incident");
    const taken = new Set((s.takenSequenceFlows ?? []).map((f) => `${f.from}->${f.to}`));
    for (const el of registry.filter((e: any) => e.type === "bpmn:SequenceFlow")) {
      if (taken.has(`${el.source?.id}->${el.target?.id}`)) canvas.addMarker(el.id, "flow-taken");
    }
  }

  summary(): string {
    const s = this.snap;
    const lines = [`Test run of ${this.processIds.join(", ")} in the test studio:`];
    lines.push(...this.log.slice(-25));
    if (s) {
      for (const i of s.instances) lines.push(`instance ${i.key}: ${i.state} vars=${JSON.stringify(i.variables)}`);
      if (s.activeElementIds.length) lines.push(`active: ${s.activeElementIds.join(", ")}`);
      if (s.incidents.length) lines.push(`incidents: ${JSON.stringify(s.incidents)}`);
    }
    return lines.join("\n");
  }

  render() {
    const s = this.snap;
    const r = this.root;
    r.replaceChildren();
    const engineKind = h("span", { class: "pill", id: "engine-kind" }, "engine …");
    this.getEngine().then((e) => {
      engineKind.textContent = e.kind === "wasm" ? "engine: WASM in view" : "engine: server";
      if (e.reason) engineKind.title = e.reason;
    });

    // Scenario from the agent
    if (this.scenario) {
      r.append(
        h("section", {}, h("h4", {}, `Agent scenario ${this.scenario.passed ? "✓ passed" : "✗ failed"}`),
          h("ol", { class: "outcomes" }, ...this.scenario.outcomes.map((o) => h("li", { class: o.ok ? "ok" : "bad" }, `${o.step.action}: ${o.detail}`)))),
      );
    }

    // Start
    const pid = h("select", {}, ...this.processIds.map((p) => h("option", { value: p }, p))) as HTMLSelectElement;
    const startVars = h("textarea", { rows: 2, placeholder: '{"amount": 100}' }) as HTMLTextAreaElement;
    r.append(
      h("section", {},
        h("div", { class: "row" }, h("h4", {}, "Start instance"), h("span", { class: "spacer" }), engineKind),
        pid, startVars,
        h("div", { class: "row" },
          h("button", { class: "primary", onclick: this.guard(() => this.exec({ op: "createInstance", processId: pid.value, variables: parseVars(startVars.value) })) }, "▶ Start"),
          h("button", { onclick: this.guard(() => this.open(this.xml, null)) }, "Reset"),
          h("button", { onclick: () => this.onReport(this.summary()), title: "Share this run with Claude" }, "Share with Claude"),
        ),
      ),
    );
    if (!s) return;

    // Jobs
    const jobs = (s.jobs ?? []).filter((j) => /created|activated|failed/i.test(String(j.state)));
    if (jobs.length) {
      r.append(h("section", {}, h("h4", {}, `Jobs (${jobs.length})`), ...jobs.map((j) => {
        const v = h("textarea", { rows: 1, placeholder: "{} result variables" }) as HTMLTextAreaElement;
        const code = h("input", { placeholder: "error code", size: 8 }) as HTMLInputElement;
        return h("div", { class: "card", onmouseenter: () => this.focus(j.elementId) },
          h("div", {}, h("b", {}, j.jobType ?? j.type), ` @ ${j.elementId} `, h("small", {}, `#${j.key} ${j.state}`)),
          v,
          h("div", { class: "row" },
            h("button", { class: "primary", onclick: this.guard(() => this.exec({ op: "completeJob", jobKey: String(j.key), variables: parseVars(v.value) })) }, "Complete"),
            code,
            h("button", { onclick: this.guard(() => this.exec({ op: "throwError", jobKey: String(j.key), errorCode: code.value || "ERROR" })) }, "Throw BPMN error"),
            h("button", { onclick: this.guard(() => this.exec({ op: "failJob", jobKey: String(j.key), retries: 0 })) }, "Fail"),
          ));
      })));
    }

    // User tasks
    const tasks = (s.userTasks ?? []).filter((t) => /created|assigned/i.test(String(t.state)));
    if (tasks.length) {
      r.append(h("section", {}, h("h4", {}, `User tasks (${tasks.length})`), ...tasks.map((t) => {
        const v = h("textarea", { rows: 1, placeholder: '{"approved": true}' }) as HTMLTextAreaElement;
        const name = this.modeler.get("elementRegistry").get(t.elementId)?.businessObject?.name ?? t.elementId;
        return h("div", { class: "card", onmouseenter: () => this.focus(t.elementId) },
          h("div", {}, h("b", {}, name), " ", h("small", {}, (t.candidateGroups ?? []).join(", "))),
          v,
          h("button", { class: "primary", onclick: this.guard(() => this.exec({ op: "completeUserTask", userTaskKey: String(t.key), variables: parseVars(v.value) })) }, "Complete task"));
      })));
    }

    // Messages / signals / time
    const subs = s.messageSubscriptions ?? [];
    const mName = h("input", { placeholder: "message name", value: String(subs[0]?.messageName ?? subs[0]?.name ?? "") }) as HTMLInputElement;
    const mKey = h("input", { placeholder: "correlation key", value: String(subs[0]?.correlationKey ?? "") }) as HTMLInputElement;
    const mVars = h("textarea", { rows: 1, placeholder: "{}" }) as HTMLTextAreaElement;
    const sigName = h("input", { placeholder: "signal name", value: String((s.signalSubscriptions ?? [])[0]?.signalName ?? "") }) as HTMLInputElement;
    const ms = h("input", { value: "60000", size: 8 }) as HTMLInputElement;
    r.append(
      h("section", {}, h("h4", {}, "Events & time"),
        subs.length ? h("small", {}, `waiting: ${subs.map((m) => `${m.messageName ?? m.name}(${m.correlationKey ?? ""})`).join(", ")}`) : null,
        h("div", { class: "row" }, mName, mKey), mVars,
        h("div", { class: "row" },
          h("button", { onclick: this.guard(() => this.exec({ op: "correlateMessage", name: mName.value, correlationKey: mKey.value, variables: parseVars(mVars.value) })) }, "Publish message"),
          sigName, h("button", { onclick: this.guard(() => this.exec({ op: "broadcastSignal", name: sigName.value })) }, "Signal")),
        h("div", { class: "row" }, h("span", {}, `clock ${fmtMs(s.now)} · timers ${(s.timers ?? []).length}`), ms,
          h("button", { onclick: this.guard(() => this.exec({ op: "advanceTime", ms: Number(ms.value) || 0 })) }, "⏩ Advance ms")),
      ),
    );

    // Instances & incidents
    r.append(h("section", {}, h("h4", {}, `Instances (${s.instances.length})`),
      ...s.instances.slice(-6).reverse().map((i) => h("div", { class: "card" },
        h("div", {}, h("b", {}, `#${i.key}`), ` ${i.processId} `, h("span", { class: `pill state-${String(i.state).toLowerCase()}` }, i.state)),
        h("pre", {}, JSON.stringify(i.variables, null, 1)))),
      ...(s.incidents ?? []).map((x) => h("div", { class: "card bad", onmouseenter: () => this.focus(x.elementId) }, `⚠ ${x.elementId}: ${x.errorMessage ?? x.message ?? JSON.stringify(x)}`)),
    ));

    r.append(h("section", {}, h("h4", {}, "Log"), h("pre", { class: "log" }, this.log.slice().reverse().join("\n"))));
  }

  private focus(id?: string) {
    if (!id) return;
    const el = this.modeler.get("elementRegistry").get(id);
    if (el) this.modeler.get("selection").select(el);
  }
}

function label(c: EngineOp): string {
  switch (c.op) {
    case "createInstance": return `start ${c.processId} ${JSON.stringify(c.variables ?? {})}`;
    case "completeJob": return `complete job ${c.jobKey} ${JSON.stringify(c.variables ?? {})}`;
    case "completeUserTask": return `complete user task ${c.userTaskKey} ${JSON.stringify(c.variables ?? {})}`;
    case "throwError": return `throw error ${c.errorCode} on job ${c.jobKey}`;
    case "failJob": return `fail job ${c.jobKey}`;
    case "correlateMessage": return `message ${c.name}(${c.correlationKey ?? ""})`;
    case "broadcastSignal": return `signal ${c.name}`;
    case "advanceTime": return `advance ${fmtMs(c.ms)}`;
    default: return c.op;
  }
}

function fmtMs(ms: number) {
  if (ms >= 86400000) return `${(ms / 86400000).toFixed(1)}d`;
  if (ms >= 3600000) return `${(ms / 3600000).toFixed(1)}h`;
  if (ms >= 60000) return `${(ms / 60000).toFixed(1)}m`;
  return `${ms}ms`;
}
