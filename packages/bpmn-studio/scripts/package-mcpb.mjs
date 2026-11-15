// Build the Claude Desktop extension (.mcpb): dist/ (server bundle, MCP App HTML, engine
// .wasm) plus a manifest. Desktop runs it with its built-in Node, so users need nothing
// installed. Usage: node scripts/package-mcpb.mjs [outDir]   (default: release/)
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const outDir = path.resolve(process.argv[2] ?? path.join(root, "release"));
if (!fs.existsSync(path.join(root, "dist/index.js"))) throw new Error("dist/ is missing: run npm run build first");

const stage = fs.mkdtempSync(path.join(os.tmpdir(), "bpmn-studio-mcpb-"));
fs.cpSync(path.join(root, "dist"), path.join(stage, "dist"), { recursive: true });
fs.cpSync(path.join(root, "README.md"), path.join(stage, "README.md"));
fs.writeFileSync(path.join(stage, "package.json"), JSON.stringify({ name: pkg.name, version: pkg.version, type: "module" }, null, 2));

const manifest = {
  manifest_version: "0.3",
  name: "bpmn-studio",
  display_name: "Camunda BPMN Studio",
  version: pkg.version,
  description: "Model, lint and test Camunda 8 BPMN processes in Claude, with an interactive bpmn.io modeler in the chat.",
  long_description:
    "Shows BPMN diagrams in an interactive bpmn.io modeler inside the conversation, so you and Claude can edit the same process. " +
    "Lints against Camunda 8 rules, and runs processes in an in-memory test engine: start instances, complete jobs and user tasks, advance time, and watch the tokens move. " +
    "Runs locally; no cluster needed.",
  author: { name: "Camunda", url: "https://camunda.com" },
  repository: { type: "git", url: "https://github.com/camunda/skills" },
  homepage: "https://github.com/camunda/skills/tree/main/plugins/bpmn-studio",
  documentation: "https://github.com/camunda/skills/tree/main/packages/bpmn-studio#readme",
  support: "https://github.com/camunda/skills/issues",
  license: pkg.license,
  keywords: pkg.keywords,
  server: {
    type: "node",
    entry_point: "dist/index.js",
    mcp_config: { command: "node", args: ["${__dirname}/dist/index.js", "--stdio"], env: { BPMN_MCP_ROOT: "${user_config.root}" } },
  },
  user_config: {
    root: {
      type: "directory",
      title: "BPMN folder",
      description: "Where relative .bpmn paths resolve and where save_bpmn may write.",
      required: false,
      default: "${DOCUMENTS}",
    },
  },
  tools_generated: true,
  compatibility: { platforms: ["darwin", "win32", "linux"], runtimes: { node: pkg.engines.node } },
};
fs.writeFileSync(path.join(stage, "manifest.json"), JSON.stringify(manifest, null, 2));

fs.mkdirSync(outDir, { recursive: true });
const out = path.join(outDir, `bpmn-studio-${pkg.version}.mcpb`);
const mcpb = ["-y", "@anthropic-ai/mcpb@2"];
execFileSync("npx", [...mcpb, "validate", path.join(stage, "manifest.json")], { stdio: "inherit" });
execFileSync("npx", [...mcpb, "pack", stage, out], { stdio: "inherit" });
fs.rmSync(stage, { recursive: true, force: true });
console.log(out);
