// Build the Claude Desktop extension (.mcpb): the bundled dist/index.js plus a manifest
// whose user_config becomes the install form (cluster address, OAuth or basic credentials).
// Desktop runs it with its built-in Node, so users need nothing installed.
// Usage: node scripts/package-mcpb.mjs [outDir]   (default: release/)
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const outDir = path.resolve(process.argv[2] ?? path.join(root, "release"));
if (!fs.existsSync(path.join(root, "dist/index.js"))) throw new Error("dist/ is missing: run npm run build first");

const stage = fs.mkdtempSync(path.join(os.tmpdir(), "cluster-mcp-mcpb-"));
fs.cpSync(path.join(root, "dist"), path.join(stage, "dist"), { recursive: true });
fs.cpSync(path.join(root, "README.md"), path.join(stage, "README.md"));
fs.writeFileSync(path.join(stage, "package.json"), JSON.stringify({ name: pkg.name, version: pkg.version, type: "module" }, null, 2));

const field = (env, spec) => ({ env, spec });
// Each entry: environment variable for the server, and the form field Desktop shows.
const fields = {
  rest_address: field("CAMUNDA_REST_ADDRESS", {
    type: "string",
    title: "Cluster address",
    description: "REST address of the Orchestration Cluster, e.g. https://bru-2.zeebe.camunda.io/<cluster-id> for SaaS or http://localhost:8080 for C8 Run.",
    default: "http://localhost:8080",
    required: true,
  }),
  client_id: field("CAMUNDA_CLIENT_ID", {
    type: "string",
    title: "OAuth client ID",
    description: "For SaaS or Self-Managed with Identity: the API client ID. Leave empty for basic auth or no auth.",
    required: false,
  }),
  client_secret: field("CAMUNDA_CLIENT_SECRET", {
    type: "string",
    title: "OAuth client secret",
    description: "The API client secret (stored in the system keychain).",
    sensitive: true,
    required: false,
  }),
  oauth_url: field("CAMUNDA_OAUTH_URL", {
    type: "string",
    title: "OAuth token URL",
    description: "Token endpoint. Leave empty for Camunda SaaS; for Self-Managed e.g. http://localhost:18080/auth/realms/camunda-platform/protocol/openid-connect/token.",
    required: false,
  }),
  audience: field("CAMUNDA_TOKEN_AUDIENCE", {
    type: "string",
    title: "OAuth audience",
    description: "Token audience, if your identity provider needs one (SaaS: leave empty).",
    required: false,
  }),
  scope: field("CAMUNDA_OAUTH_SCOPE", {
    type: "string",
    title: "OAuth scope",
    description: "Token scope, if your identity provider needs one.",
    required: false,
  }),
  username: field("CAMUNDA_BASIC_AUTH_USERNAME", {
    type: "string",
    title: "Basic auth username",
    description: "For C8 Run or Self-Managed with basic authentication. Leave empty for OAuth or no auth.",
    required: false,
  }),
  password: field("CAMUNDA_BASIC_AUTH_PASSWORD", {
    type: "string",
    title: "Basic auth password",
    description: "Basic auth password (stored in the system keychain).",
    sensitive: true,
    required: false,
  }),
  poll_seconds: field("CAMUNDA_MCP_POLL_SECONDS", {
    type: "number",
    title: "Tool refresh interval (seconds)",
    description: "How often to check for newly deployed processes. 0 turns it off.",
    default: 30,
    min: 0,
    max: 3600,
    required: false,
  }),
};

const manifest = {
  manifest_version: "0.3",
  name: "camunda-cluster",
  display_name: "Camunda 8 Cluster",
  version: pkg.version,
  description: "Operate a Camunda 8 cluster from Claude: process instances, incidents, user tasks, variables, and deployed processes as tools.",
  long_description:
    "Connects Claude to the built-in MCP servers of a Camunda 8.9+ Orchestration Cluster (SaaS, Self-Managed or C8 Run). " +
    "Search and inspect process instances, incidents, user tasks and variables; resolve incidents and complete tasks; and start any deployed process that has an MCP start event. " +
    "Authenticates with OAuth client credentials or basic auth, and picks up processes deployed during a conversation.",
  author: { name: "Camunda", url: "https://camunda.com" },
  repository: { type: "git", url: "https://github.com/camunda/skills" },
  homepage: "https://github.com/camunda/skills/tree/main/packages/cluster-mcp",
  documentation: "https://github.com/camunda/skills/tree/main/packages/cluster-mcp#readme",
  support: "https://github.com/camunda/skills/issues",
  license: pkg.license,
  keywords: pkg.keywords,
  server: {
    type: "node",
    entry_point: "dist/index.js",
    mcp_config: {
      command: "node",
      args: ["${__dirname}/dist/index.js"],
      env: Object.fromEntries(Object.entries(fields).map(([key, f]) => [f.env, `\${user_config.${key}}`])),
    },
  },
  tools_generated: true,
  user_config: Object.fromEntries(Object.entries(fields).map(([key, f]) => [key, f.spec])),
  compatibility: { platforms: ["darwin", "win32", "linux"], runtimes: { node: pkg.engines.node } },
};
fs.writeFileSync(path.join(stage, "manifest.json"), JSON.stringify(manifest, null, 2));

fs.mkdirSync(outDir, { recursive: true });
const out = path.join(outDir, `camunda-cluster-${pkg.version}.mcpb`);
const mcpb = ["-y", "@anthropic-ai/mcpb@2"];
execFileSync("npx", [...mcpb, "validate", path.join(stage, "manifest.json")], { stdio: "inherit" });
execFileSync("npx", [...mcpb, "pack", stage, out], { stdio: "inherit" });
fs.rmSync(stage, { recursive: true, force: true });
console.log(out);
