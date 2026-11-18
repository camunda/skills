import { Client } from "@modelcontextprotocol/client";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import type { Endpoint } from "./config.js";

export type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export interface AuthSource {
  getAuthHeaders(): Promise<Record<string, string>>;
  forceAuthRefresh(): Promise<unknown>;
}

/** fetch that adds Camunda auth headers and retries once with a fresh token on 401. */
/** Per-request timeout for MCP calls (POST), so a hung cluster can't stall polling forever. */
export const REQUEST_TIMEOUT_MS = 30_000;

export function authFetch(auth: AuthSource, timeoutMs = REQUEST_TIMEOUT_MS): FetchLike {
  const withAuth = async (init: RequestInit | undefined) => {
    const headers = new Headers(init?.headers);
    for (const [k, v] of Object.entries(await auth.getAuthHeaders())) headers.set(k, v);
    // Only requests get a deadline; the client's GET event stream is meant to stay open.
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "GET" || timeoutMs <= 0) return { ...init, headers };
    const timeout = AbortSignal.timeout(timeoutMs);
    return { ...init, headers, signal: init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout };
  };
  return async (input, init) => {
    const res = await fetch(input, await withAuth(init));
    if (res.status !== 401) return res;
    await auth.forceAuthRefresh();
    return fetch(input, await withAuth(init));
  };
}

export interface Tool {
  name: string;
  description?: string;
  inputSchema: Record<string, unknown>;
  [key: string]: unknown;
}

type State = "idle" | "connected" | "error";

/** One remote MCP server on the cluster (/mcp/cluster or /mcp/processes). */
export class Backend {
  state: State = "idle";
  lastError?: string;
  tools: Tool[] = [];
  instructions?: string;
  serverName?: string;
  private client?: Client;

  constructor(
    readonly endpoint: Endpoint,
    private readonly fetchImpl: FetchLike,
    private readonly clientVersion: string,
  ) {}

  async ensureConnected(): Promise<Client> {
    if (this.client && this.state === "connected") return this.client;
    await this.client?.close().catch(() => {});
    const client = new Client({ name: "camunda-cluster-mcp", version: this.clientVersion });
    const transport = new StreamableHTTPClientTransport(this.endpoint.url, { fetch: this.fetchImpl });
    try {
      await client.connect(transport);
    } catch (err) {
      this.client = undefined;
      this.fail(err);
      throw err;
    }
    this.client = client;
    this.state = "connected";
    this.lastError = undefined;
    this.instructions = client.getInstructions();
    this.serverName = client.getServerVersion()?.name;
    return client;
  }

  /** Re-read the tool list; on failure keep nothing so stale tools are not offered. */
  async refresh(): Promise<void> {
    try {
      const client = await this.ensureConnected();
      const tools: Tool[] = [];
      let cursor: string | undefined;
      do {
        const page = await client.listTools(cursor ? { cursor } : undefined);
        tools.push(...(page.tools as Tool[]));
        cursor = page.nextCursor;
      } while (cursor);
      this.tools = tools;
    } catch (err) {
      this.fail(err);
      this.tools = [];
    }
  }

  async callTool(name: string, args: Record<string, unknown> | undefined) {
    const client = await this.ensureConnected();
    try {
      return await client.callTool({ name, arguments: args ?? {} });
    } catch (err) {
      // A transport failure (cluster restarted, network) forces a reconnect next time.
      if (!isMcpProtocolError(err)) this.fail(err);
      throw err;
    }
  }

  async close() {
    await this.client?.close().catch(() => {});
  }

  private fail(err: unknown) {
    this.state = "error";
    this.lastError = describeError(err, this.endpoint);
  }
}

function isMcpProtocolError(err: unknown): boolean {
  return typeof err === "object" && err !== null && "code" in err && typeof (err as { code: unknown }).code === "number";
}

/** Messages and error codes along the cause chain (fetch hides ECONNREFUSED a few levels down). */
function errorChain(err: unknown, depth = 0): string[] {
  if (depth > 5 || err === null || err === undefined) return [];
  if (typeof err !== "object") return [String(err)];
  const e = err as { message?: unknown; code?: unknown; cause?: unknown; errors?: unknown; status?: unknown; data?: { status?: unknown } };
  const out: string[] = [];
  // The MCP SDK's SdkHttpError keeps the status in data.status, not in the message.
  const status = typeof e.status === "number" ? e.status : typeof e.data?.status === "number" ? e.data.status : undefined;
  if (status !== undefined) out.push(`HTTP ${status}`);
  if (typeof e.message === "string" && e.message.trim()) out.push(e.message.trim());
  if (typeof e.code === "string") out.push(e.code);
  if (Array.isArray(e.errors)) for (const sub of e.errors) out.push(...errorChain(sub, depth + 1));
  out.push(...errorChain(e.cause, depth + 1));
  return [...new Set(out)];
}

export function describeError(err: unknown, endpoint: Endpoint): string {
  const chain = errorChain(err);
  const all = chain.join(" ");
  if (/\b404\b/.test(all)) return `${endpoint.url} returned 404: the MCP gateway is disabled on this cluster or the version is older than 8.9`;
  if (/\b(401|403)\b/.test(all)) return `${endpoint.url} rejected the credentials (${chain.join(": ")}); check the client id/secret or username/password, and the audience`;
  const net = all.match(/ECONNREFUSED|ENOTFOUND|EAI_AGAIN|ETIMEDOUT|ECONNRESET|CERT_[A-Z_]+|UNABLE_TO_[A-Z_]+|SELF_SIGNED[A-Z_]*/);
  if (net) return `cannot reach ${endpoint.url} (${net[0]}): is the cluster running and the address right?`;
  return `${endpoint.url}: ${chain.join(": ") || "unknown error"}`;
}

/** Where a tool we offer really lives: which backend, and its name there. */
export interface Route {
  backend: Backend;
  remote: string;
}

export interface Merged {
  tools: Tool[];
  owner: Map<string, Route>;
  /** Tools from /mcp/processes, under the names we offer them as. */
  processTools: Tool[];
}

/**
 * The cluster names a process tool `<io.camunda.tool:name>_<start event subscription key>`,
 * and the key changes on every deploy. Offer it as the plain `<name>` so a redeployed
 * process keeps its tool name (hosts that cache the tool list keep working).
 */
export function stableName(name: string): string {
  return name.replace(/_\d{6,}$/, "") || name;
}

/**
 * Merge the tool lists: earlier backends win on name clashes (/mcp/cluster before
 * /mcp/processes), so a process named like an ops tool can't shadow it. Process tools get
 * stable names unless that would clash.
 */
export function mergeTools(backends: Backend[]): Merged {
  const owner = new Map<string, Route>();
  const tools: Tool[] = [];
  const processTools: Tool[] = [];
  for (const b of backends) {
    const isProcesses = b.endpoint.path.endsWith("/processes");
    const stableCount = new Map<string, number>();
    if (isProcesses) for (const t of b.tools) stableCount.set(stableName(t.name), (stableCount.get(stableName(t.name)) ?? 0) + 1);
    for (const t of b.tools) {
      if (owner.has(t.name)) continue; // e.g. searchIncidents is offered by both servers
      const stable = stableName(t.name);
      const name = isProcesses && stable !== t.name && stableCount.get(stable) === 1 && !owner.has(stable) ? stable : t.name;
      if (owner.has(name)) continue;
      owner.set(name, { backend: b, remote: t.name });
      const offered = name === t.name ? t : { ...t, name };
      tools.push(offered);
      if (isProcesses && /_\d{6,}$/.test(t.name)) processTools.push(offered);
    }
  }
  return { tools, owner, processTools };
}

/** Stable fingerprint of a tool list, to detect changes between polls. */
export function fingerprint(tools: Tool[]): string {
  return JSON.stringify(
    tools
      .map((t) => [t.name, t.description ?? "", t.inputSchema] as const)
      .sort((a, b) => a[0].localeCompare(b[0])),
  );
}
