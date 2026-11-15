// Checks that the bpmn-studio plugin and the @camunda8/bpmn-studio package agree:
// package.json, the plugin manifest and both marketplace entries carry the same version,
// and .mcp.json runs the package with a range that includes it (same major).
// usage (from the repo root): node packages/bpmn-studio/scripts/check-plugin.mjs
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../..");
const read = (rel) => JSON.parse(fs.readFileSync(path.join(root, rel), "utf8"));
const problems = [];

const pkg = read("packages/bpmn-studio/package.json");
const version = pkg.version;
const versions = {
  "packages/bpmn-studio/package.json": version,
  "plugins/bpmn-studio/.claude-plugin/plugin.json": read("plugins/bpmn-studio/.claude-plugin/plugin.json").version,
};
for (const m of [".claude-plugin/marketplace.json", ".github/plugin/marketplace.json"]) {
  const entry = read(m).plugins.find((p) => p.name === "bpmn-studio");
  if (!entry) problems.push(`${m}: no bpmn-studio plugin entry`);
  else {
    versions[m] = entry.version;
    if (entry.source !== "./plugins/bpmn-studio") problems.push(`${m}: bpmn-studio source is ${entry.source}, expected ./plugins/bpmn-studio`);
  }
}
for (const [file, v] of Object.entries(versions)) {
  if (v !== version) problems.push(`${file}: version ${v}, expected ${version} (packages/bpmn-studio/package.json)`);
}

const server = read("plugins/bpmn-studio/.mcp.json").mcpServers?.["bpmn-studio"];
const spec = server?.args?.find((a) => typeof a === "string" && a.startsWith(`${pkg.name}@`));
if (!spec) problems.push(`plugins/bpmn-studio/.mcp.json: no "${pkg.name}@<major>" argument`);
else {
  const range = spec.slice(pkg.name.length + 1);
  if (range !== version.split(".")[0]) problems.push(`plugins/bpmn-studio/.mcp.json: runs ${spec}, expected ${pkg.name}@${version.split(".")[0]} (major of ${version})`);
}

if (!fs.existsSync(path.join(root, "plugins/bpmn-studio/skills/bpmn-studio/SKILL.md"))) problems.push("plugins/bpmn-studio/skills/bpmn-studio/SKILL.md is missing");

if (problems.length) {
  console.error(`bpmn-studio plugin check failed:\n- ${problems.join("\n- ")}`);
  process.exit(1);
}
console.log(`bpmn-studio plugin check OK (${pkg.name}@${version}, ${Object.keys(versions).length} manifests)`);
