import { BpmnModdle } from "bpmn-moddle";
import zeebeModdle from "zeebe-bpmn-moddle/resources/zeebe.json";
import modelerModdle from "modeler-moddle/resources/modeler.json";
// @ts-ignore — CJS without types
import { Linter } from "bpmnlint";
// @ts-ignore
import StaticResolver from "bpmnlint/lib/resolver/static-resolver";
import { lintCache, compatConfigNames } from "./lint-rules.gen";

export interface LintIssue {
  id: string;
  message: string;
  category: string;
  rule?: string;
  name?: string;
}

export interface LintResult {
  ok: boolean;
  errorCount: number;
  warningCount: number;
  issues: LintIssue[];
  /** Rulesets applied, same as `c8ctl --dry-run bpmn lint` config.extends */
  extends: string[];
  /** Set when the Camunda ruleset could not be selected (no executionPlatformVersion). */
  rulesetWarning?: string;
  parseError?: string;
}

const moddle = new BpmnModdle({ zeebe: zeebeModdle, modeler: modelerModdle });
const compatConfigs = compatConfigNames.filter((k) => /^camunda-cloud-\d+-\d+$/.test(k));

function compatConfigFor(root: any): { config?: string; warning?: string } {
  const platform = root.get?.("modeler:executionPlatform") ?? root.$attrs?.["modeler:executionPlatform"];
  const version = root.get?.("modeler:executionPlatformVersion") ?? root.$attrs?.["modeler:executionPlatformVersion"];
  if (!version || (platform && platform !== "Camunda Cloud")) {
    return {
      warning:
        'No modeler:executionPlatform="Camunda Cloud" modeler:executionPlatformVersion on <bpmn:definitions>: Camunda 8 rules were NOT applied. Add e.g. modeler:executionPlatformVersion="8.8.0".',
    };
  }
  const [maj, min] = String(version).split(".").map(Number);
  const exact = `camunda-cloud-${maj}-${min}`;
  if (compatConfigs.includes(exact)) return { config: `plugin:camunda-compat/${exact}` };
  const highest = compatConfigs.sort((a, b) => {
    const [, , a1, a2] = a.split("-").map(Number);
    const [, , b1, b2] = b.split("-").map(Number);
    return a1 - b1 || a2 - b2;
  }).at(-1)!;
  return { config: `plugin:camunda-compat/${highest}`, warning: `No camunda-compat ruleset for ${version}; used ${highest}.` };
}

/**
 * Lint BPMN XML exactly like `c8ctl bpmn lint`: bpmnlint:recommended plus the
 * camunda-compat ruleset matching modeler:executionPlatformVersion.
 */
export async function lintBpmn(xml: string): Promise<LintResult> {
  let root: any;
  try {
    ({ rootElement: root } = await moddle.fromXML(xml, "bpmn:Definitions"));
  } catch (e) {
    return { ok: false, errorCount: 1, warningCount: 0, issues: [], extends: [], parseError: e instanceof Error ? e.message : String(e) };
  }
  const { config: compatConfig, warning } = compatConfigFor(root);
  const config = { extends: ["bpmnlint:recommended", ...(compatConfig ? [compatConfig] : [])] };
  const linter = new Linter({ config, resolver: new StaticResolver(lintCache) });
  const results: Record<string, Array<Record<string, any>>> = await linter.lint(root);
  const issues: LintIssue[] = [];
  for (const [rule, reports] of Object.entries(results)) {
    for (const r of reports) {
      issues.push({ id: String(r.id ?? ""), message: String(r.message ?? ""), category: r.category === "error" ? "error" : "warn", rule, name: r.name });
    }
  }
  const errorCount = issues.filter((i) => i.category === "error").length;
  const warningCount = issues.length - errorCount;
  return { ok: errorCount === 0 && warningCount === 0 && !!compatConfig, errorCount, warningCount, issues, extends: config.extends, rulesetWarning: warning };
}

export function formatLint(r: LintResult): string {
  if (r.parseError) return `BPMN could not be parsed: ${r.parseError}`;
  const head = `lint: ${r.errorCount} error(s), ${r.warningCount} warning(s)${r.ok ? " — clean" : ""} [${r.extends.join(", ")}]`;
  const lines = r.issues.map((i) => `- [${i.category}] ${i.id}: ${i.message} (${i.rule})`);
  return [head, r.rulesetWarning ? `WARNING: ${r.rulesetWarning}` : "", ...lines].filter(Boolean).join("\n");
}
