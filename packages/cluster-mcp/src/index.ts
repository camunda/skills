// camunda-cluster-mcp: a local stdio MCP server in front of a Camunda 8 cluster's built-in
// MCP servers. It authenticates with the Camunda SDK (OAuth client credentials, basic or
// none), merges /mcp/cluster and /mcp/processes into one tool list, and polls that list so
// processes deployed mid-session show up (the cluster's servers are stateless and never send
// notifications/tools/list_changed themselves).

// The Camunda SDK logs through console.info/debug, which would land on stdout and corrupt
// the stdio protocol. The MCP transport writes to process.stdout directly, so send console
// output to stderr before anything else runs.
console.log = console.error;
console.info = console.error;
console.debug = console.error;

import { createCamundaClient } from "@camunda8/orchestration-cluster-api";
import { Server } from "@modelcontextprotocol/server";
import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import { authFetch, Backend, fingerprint, mergeTools, type AuthSource } from "./backend.js";
import { resolveConfig } from "./config.js";

declare const __VERSION__: string;
const VERSION = typeof __VERSION__ === "string" ? __VERSION__ : "0.0.0-dev";
const STATUS_TOOL = "camunda_connection_status";
const LIST_PROCESS_TOOLS = "camunda_process_tools";
const CALL_PROCESS_TOOL = "camunda_call_process_tool";
const CONNECT_TIMEOUT_MS = 10_000;

const log = (...args: unknown[]) => console.error("[camunda-cluster-mcp]", ...args);

if (process.argv.includes("--version")) {
  console.error(VERSION);
  process.exit(0);
}
if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.error(`camunda-cluster-mcp ${VERSION}

Local MCP server (stdio) for a Camunda 8.9+ Orchestration Cluster. Configure it with the
Camunda SDK environment variables:

  CAMUNDA_REST_ADDRESS         cluster REST address (default http://localhost:8080; /v2 is optional)
  CAMUNDA_AUTH_STRATEGY        NONE | BASIC | OAUTH (inferred from the credentials when unset)
  CAMUNDA_CLIENT_ID / CAMUNDA_CLIENT_SECRET          OAuth client credentials
  CAMUNDA_OAUTH_URL / CAMUNDA_TOKEN_AUDIENCE / CAMUNDA_OAUTH_SCOPE
  CAMUNDA_BASIC_AUTH_USERNAME / CAMUNDA_BASIC_AUTH_PASSWORD

  CAMUNDA_MCP_SERVERS          which cluster servers to use: cluster,processes (default both)
  CAMUNDA_MCP_POLL_SECONDS     how often to re-read the tool list (default 30, 0 = off)
`);
  process.exit(0);
}

const config = resolveConfig();
const camunda = createCamundaClient({ config: config.sdkConfig as never });
const auth: AuthSource = {
  getAuthHeaders: () => camunda.getAuthHeaders(),
  forceAuthRefresh: () => camunda.forceAuthRefresh(),
};
const fetchImpl = authFetch(auth);
const backends = config.endpoints.map((e) => new Backend(e, fetchImpl, VERSION));
log(`cluster ${config.baseUrl} (auth ${config.authStrategy}); servers: ${config.endpoints.map((e) => e.path).join(", ")}`);

// Connect up front so the remote instructions can go into our initialize result. Don't
// block startup on a cluster that is down: the poller keeps retrying.
let refreshing: Promise<void> | undefined;
async function refreshAll(): Promise<void> {
  refreshing ??= Promise.all(backends.map((b) => b.refresh()))
    .then(() => {
      for (const b of backends) if (b.state === "error") log(b.lastError);
    })
    .finally(() => {
      refreshing = undefined;
    });
  return refreshing;
}
await Promise.race([refreshAll(), new Promise((r) => setTimeout(r, CONNECT_TIMEOUT_MS))]);

function instructions(): string {
  const parts = [
    `Tools for the Camunda 8 cluster at ${config.baseUrl}. ` +
      `Process tools (from /mcp/processes) appear as processes with an MCP start event are deployed; ` +
      `the list refreshes ${config.pollSeconds > 0 ? `every ${config.pollSeconds}s` : "on reconnect"}. ` +
      `Some hosts only read the tool list once per session: if a process tool you expect isn't in your tool list, ` +
      `call ${LIST_PROCESS_TOOLS} to see what is deployed now and ${CALL_PROCESS_TOOL} to run it. ` +
      `If tools are missing or failing, call ${STATUS_TOOL}.`,
  ];
  for (const b of backends) if (b.instructions) parts.push(`## ${b.endpoint.path}\n${b.instructions.trim()}`);
  return parts.join("\n\n");
}

const statusTool = {
  name: STATUS_TOOL,
  description:
    "Show how this connector is connected to the Camunda cluster: address, auth strategy, and for each cluster MCP server whether it is reachable, how many tools it offers, and the last error. Use it when Camunda tools are missing or fail.",
  inputSchema: { type: "object" as const, properties: {} },
  annotations: { readOnlyHint: true },
};

// Hosts like Claude Desktop take the tool list once per connection and ignore
// tools/list_changed, so processes deployed later would be unreachable. These two fixed
// tools always see the live list.
const listProcessToolsTool = {
  name: LIST_PROCESS_TOOLS,
  description:
    "List the processes on the Camunda cluster that can be started as tools right now (deployed processes with an MCP start event), with their purpose and input schema. Use it when a process tool you expect is not in your tool list, e.g. one deployed during this conversation; then start it with " +
    CALL_PROCESS_TOOL +
    ".",
  inputSchema: { type: "object" as const, properties: {} },
  annotations: { readOnlyHint: true },
};

const callProcessToolTool = {
  name: CALL_PROCESS_TOOL,
  description:
    "Start a process tool on the Camunda cluster by name, for process tools not in your tool list (see " +
    LIST_PROCESS_TOOLS +
    "). This starts a process instance.",
  inputSchema: {
    type: "object" as const,
    properties: {
      name: { type: "string", description: `Tool name as listed by ${LIST_PROCESS_TOOLS}, e.g. "greet".` },
      arguments: { type: "object", description: "Arguments matching the tool's input schema.", additionalProperties: true },
    },
    required: ["name"],
  },
};

const localTools = [listProcessToolsTool, callProcessToolTool, statusTool];

async function latest() {
  await refreshAll();
  current = mergeTools(backends);
  lastPrint = fingerprint(current.tools);
  return current;
}

async function callRemote(name: string, args: Record<string, unknown> | undefined) {
  let route = current.owner.get(name);
  // Unknown (deployed since the last refresh), or a process tool: its key changes on every
  // deploy, so resolve it against the live list.
  if (!route || route.remote !== name) route = (await latest()).owner.get(name);
  if (!route) {
    return {
      isError: true,
      content: [{ type: "text" as const, text: `Unknown tool "${name}". It may have been undeployed, or the cluster is unreachable; call ${LIST_PROCESS_TOOLS} or ${STATUS_TOOL}.` }],
    };
  }
  try {
    return (await route.backend.callTool(route.remote, args)) as never;
  } catch (err) {
    return {
      isError: true,
      content: [{ type: "text" as const, text: `${route.backend.endpoint.path} failed: ${err instanceof Error ? err.message : String(err)}` }],
    };
  }
}

function status() {
  return {
    connector: `camunda-cluster-mcp ${VERSION}`,
    cluster: config.baseUrl,
    auth: config.authStrategy,
    pollSeconds: config.pollSeconds,
    servers: backends.map((b) => ({
      path: b.endpoint.path,
      url: b.endpoint.url.toString(),
      state: b.state,
      tools: b.tools.length,
      ...(b.serverName ? { server: b.serverName } : {}),
      ...(b.lastError ? { error: b.lastError } : {}),
    })),
  };
}

const server = new Server(
  { name: "camunda-cluster", version: VERSION },
  { capabilities: { tools: { listChanged: true } }, instructions: instructions() },
);

let current = mergeTools(backends);
let lastPrint = fingerprint(current.tools);

server.setRequestHandler("tools/list", async () => {
  // Serve live data; the poll only exists to tell clients when to ask again.
  return { tools: [...(await latest()).tools, ...localTools] as never };
});

server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;
  if (name === STATUS_TOOL) {
    return { content: [{ type: "text", text: JSON.stringify(status(), null, 2) }] };
  }
  if (name === LIST_PROCESS_TOOLS) {
    const { processTools } = await latest();
    const list = processTools.map((t) => ({ name: t.name, description: t.description, inputSchema: t.inputSchema }));
    const text = list.length
      ? JSON.stringify(list, null, 2)
      : `No process tools are deployed. A process becomes a tool when its start event is a message start event with the zeebe property io.camunda.tool:name.${backends.some((b) => b.state === "error") ? ` Some cluster servers are unreachable; call ${STATUS_TOOL}.` : ""}`;
    return { content: [{ type: "text", text }] };
  }
  if (name === CALL_PROCESS_TOOL) {
    const target = typeof args?.name === "string" ? args.name : "";
    const { processTools } = await latest();
    if (!processTools.some((t) => t.name === target)) {
      return {
        isError: true,
        content: [{ type: "text", text: `No process tool "${target}". Available: ${processTools.map((t) => t.name).join(", ") || "none"}.` }],
      };
    }
    const inner = args?.arguments;
    return callRemote(target, inner && typeof inner === "object" ? (inner as Record<string, unknown>) : {});
  }
  return callRemote(name, args);
});

let initialized = false;
server.oninitialized = () => {
  initialized = true;
};

if (config.pollSeconds > 0) {
  const timer = setInterval(async () => {
    await refreshAll();
    const next = mergeTools(backends);
    const print = fingerprint(next.tools);
    if (print === lastPrint) return;
    current = next;
    lastPrint = print;
    log(`tool list changed (${next.tools.length} tools)`);
    if (initialized) await server.sendToolListChanged().catch((err: unknown) => log("list_changed failed:", err));
  }, config.pollSeconds * 1000);
  timer.unref();
}

const shutdown = async () => {
  await Promise.all(backends.map((b) => b.close()));
  process.exit(0);
};
process.stdin.on("end", shutdown);
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

await server.connect(new StdioServerTransport());
log("ready");
