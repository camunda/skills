// Headless check against a fake cluster (no Camunda needed): two stateless MCP endpoints
// like /mcp/cluster and /mcp/processes, plus an OAuth token endpoint. Covers OAuth with a
// token refresh after 401, basic auth, unset Desktop placeholders, tool merge/dedupe, call
// routing, forwarded instructions and tools/list_changed after a "deploy".
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { NodeStreamableHTTPServerTransport } from "@modelcontextprotocol/node";
import { Server } from "@modelcontextprotocol/server";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ok = (m) => console.log("✓", m);

// ---- fake cluster ---------------------------------------------------------------
const tool = (name, description) => ({ name, description, inputSchema: { type: "object", properties: {} } });
const remote = {
  cluster: { tools: [tool("searchIncidents", "cluster: search incidents"), tool("getTopology", "cluster: topology")], instructions: "CLUSTER-INSTRUCTIONS" },
  processes: { tools: [tool("searchIncidents", "processes: search incidents"), tool("greet_1", "Start greet")], instructions: "PROCESSES-INSTRUCTIONS" },
};
const auth = { mode: "oauth", validToken: "", issued: 0, basic: "Basic " + Buffer.from("demo:secret").toString("base64"), seen: [] };

function mcpServerFor(name) {
  const s = new Server({ name: `fake ${name}`, version: "1" }, { capabilities: { tools: { listChanged: false } }, instructions: remote[name].instructions });
  s.setRequestHandler("tools/list", async () => ({ tools: remote[name].tools }));
  s.setRequestHandler("tools/call", async (req) => ({ content: [{ type: "text", text: `${name} ran ${req.params.name}` }] }));
  return s;
}

const httpServer = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  if (url.pathname === "/oauth/token") {
    auth.issued++;
    auth.validToken = `tok-${auth.issued}`;
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ access_token: auth.validToken, token_type: "Bearer", expires_in: 3600 }));
  }
  const m = url.pathname.match(/^\/mcp\/(cluster|processes)$/);
  if (!m) {
    res.writeHead(404);
    return res.end();
  }
  const header = req.headers.authorization ?? "";
  auth.seen.push(header);
  const allowed = auth.mode === "oauth" ? header === `Bearer ${auth.validToken}` : header === auth.basic;
  if (!allowed) {
    res.writeHead(401);
    return res.end();
  }
  // Stateless, like the real gateway: a fresh server and transport per request.
  const transport = new NodeStreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
  const server = mcpServerFor(m[1]);
  res.on("close", () => {
    transport.close();
    server.close();
  });
  await server.connect(transport);
  await transport.handleRequest(req, res);
});
await new Promise((r) => httpServer.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${httpServer.address().port}`;
const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cluster-mcp-smoke-"));

async function connect(env) {
  const client = new Client({ name: "smoke", version: "0" });
  const events = { listChanged: 0 };
  client.setNotificationHandler("notifications/tools/list_changed", () => {
    events.listChanged++;
  });
  const clean = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith("CAMUNDA_")));
  await client.connect(
    new StdioClientTransport({
      command: process.execPath,
      args: [path.join(root, "dist/index.js")],
      env: { ...clean, CAMUNDA_REST_ADDRESS: `${base}/v2`, CAMUNDA_MCP_POLL_SECONDS: "1", CAMUNDA_OAUTH_CACHE_DIR: cacheDir, ...env },
      stderr: "pipe",
    }),
  );
  return { client, events };
}

const waitFor = async (pred, ms = 10_000) => {
  const t0 = Date.now();
  while (!pred()) {
    if (Date.now() - t0 > ms) throw new Error("timed out");
    await new Promise((r) => setTimeout(r, 100));
  }
};

try {
  // ---- OAuth ----------------------------------------------------------------------
  {
    const { client, events } = await connect({
      CAMUNDA_CLIENT_ID: "smoke",
      CAMUNDA_CLIENT_SECRET: "smoke-secret",
      CAMUNDA_OAUTH_URL: `${base}/oauth/token`,
      CAMUNDA_TOKEN_AUDIENCE: "zeebe-api",
      // Desktop leaves untouched optional fields as placeholders: they must be ignored.
      CAMUNDA_OAUTH_SCOPE: "${user_config.oauth_scope}",
      CAMUNDA_BASIC_AUTH_USERNAME: "",
    });
    assert.deepEqual(client.getServerCapabilities()?.tools, { listChanged: true });
    const instructions = client.getInstructions() ?? "";
    assert(instructions.includes("CLUSTER-INSTRUCTIONS") && instructions.includes("PROCESSES-INSTRUCTIONS"), "instructions forwarded");
    ok("capabilities + forwarded instructions");

    const names = (await client.listTools()).tools.map((t) => t.name).sort();
    assert.deepEqual(names, ["camunda_connection_status", "getTopology", "greet_1", "searchIncidents"]);
    assert(auth.seen.some((h) => h.startsWith("Bearer tok-")), "bearer token sent");
    ok(`OAuth bearer + merged tools: ${names.join(", ")}`);

    const r = await client.callTool({ name: "searchIncidents", arguments: {} });
    assert.equal(r.content[0].text, "cluster ran searchIncidents");
    const g = await client.callTool({ name: "greet_1", arguments: {} });
    assert.equal(g.content[0].text, "processes ran greet_1");
    ok("routing: duplicate goes to /mcp/cluster, process tool to /mcp/processes");

    // Revoke the token: the next call gets 401 and must succeed after one refresh.
    const before = auth.issued;
    auth.validToken = "revoked-" + Date.now();
    const again = await client.callTool({ name: "getTopology", arguments: {} });
    assert.equal(again.content[0].text, "cluster ran getTopology");
    assert(auth.issued > before, "token refreshed");
    ok("401 -> token refresh -> retry");

    // "Deploy" a process tool: the poll must notify the client.
    remote.processes.tools.push(tool("approve_2", "Start approval"));
    await waitFor(() => events.listChanged > 0);
    const after = (await client.listTools()).tools.map((t) => t.name);
    assert(after.includes("approve_2"));
    ok("tools/list_changed after deploy, new tool listed");

    const status = JSON.parse((await client.callTool({ name: "camunda_connection_status", arguments: {} })).content[0].text);
    assert.equal(status.auth, "OAUTH");
    assert.equal(status.cluster, base);
    assert(status.servers.every((s) => s.state === "connected"));
    ok("status tool");
    await client.close();
  }

  // ---- Basic auth -----------------------------------------------------------------
  {
    auth.mode = "basic";
    auth.seen.length = 0;
    const { client } = await connect({
      CAMUNDA_BASIC_AUTH_USERNAME: "demo",
      CAMUNDA_BASIC_AUTH_PASSWORD: "secret",
      CAMUNDA_CLIENT_ID: "${user_config.client_id}",
      CAMUNDA_CLIENT_SECRET: "${user_config.client_secret}",
      CAMUNDA_MCP_SERVERS: "cluster",
    });
    const names = (await client.listTools()).tools.map((t) => t.name).sort();
    assert.deepEqual(names, ["camunda_connection_status", "getTopology", "searchIncidents"]);
    assert(auth.seen.every((h) => h === auth.basic), "basic header on every request");
    ok("basic auth (placeholders ignored), CAMUNDA_MCP_SERVERS=cluster");
    await client.close();
  }

  // ---- Unreachable endpoint ---------------------------------------------------------
  {
    const { client } = await connect({ CAMUNDA_REST_ADDRESS: `${base}/nope`, CAMUNDA_AUTH_STRATEGY: "NONE" });
    const names = (await client.listTools()).tools.map((t) => t.name);
    assert.deepEqual(names, ["camunda_connection_status"]);
    const status = JSON.parse((await client.callTool({ name: "camunda_connection_status", arguments: {} })).content[0].text);
    assert.match(status.servers[0].error, /404: the MCP gateway is disabled/);
    ok("404 reported by the status tool, server stays up");
    await client.close();
  }
  console.log("smoke passed");
} finally {
  httpServer.close();
  fs.rmSync(cacheDir, { recursive: true, force: true });
}
