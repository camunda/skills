// Connection settings come from the standard Camunda SDK environment variables
// (CAMUNDA_REST_ADDRESS, CAMUNDA_CLIENT_ID, ...), so an existing SDK .env works as is.
// Claude Desktop (.mcpb) fills the same variables from its settings form; fields the
// user leaves empty can arrive as "" or as the literal "${user_config.x}" placeholder,
// so both count as unset.

export interface Endpoint {
  /** Short name used in logs and tool routing, e.g. "cluster". */
  name: string;
  /** MCP path on the cluster, e.g. /mcp/cluster. */
  path: string;
  url: URL;
}

export interface ProxyConfig {
  /** Cluster REST address without the /v2 suffix. */
  baseUrl: string;
  endpoints: Endpoint[];
  /** Seconds between tool list refreshes; 0 disables polling. */
  pollSeconds: number;
  /** Settings handed to the Camunda SDK (auth only; the SDK never calls the REST API here). */
  sdkConfig: Record<string, string>;
  authStrategy: "NONE" | "BASIC" | "OAUTH";
}

const DEFAULT_ADDRESS = "http://localhost:8080";

export function isUnset(value: string | undefined): boolean {
  if (value === undefined) return true;
  const v = value.trim();
  return v === "" || /^\$\{[^}]*\}$/.test(v);
}

/** Drop empty and unsubstituted placeholder values so neither we nor the SDK read them. */
export function scrubEnv(env: NodeJS.ProcessEnv): void {
  for (const key of Object.keys(env)) {
    if ((key.startsWith("CAMUNDA_") || key.startsWith("ZEEBE_")) && isUnset(env[key])) delete env[key];
  }
}

export function normalizeBaseUrl(address: string): string {
  let url = address.trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(url)) url = `http://${url}`;
  return url.replace(/\/v2$/i, "");
}

export function resolveConfig(env: NodeJS.ProcessEnv = process.env): ProxyConfig {
  scrubEnv(env);
  // CAMUNDA_BASE_URL is what c8ctl reads; accept it too so a c8ctl-style env works.
  const address = env.CAMUNDA_REST_ADDRESS ?? env.CAMUNDA_BASE_URL ?? DEFAULT_ADDRESS;
  const baseUrl = normalizeBaseUrl(address);

  const sdkConfig: Record<string, string> = {};
  for (const [key, value] of Object.entries(env)) {
    if (key.startsWith("CAMUNDA_") && value !== undefined) sdkConfig[key] = value;
  }
  sdkConfig.CAMUNDA_REST_ADDRESS = baseUrl;
  delete sdkConfig.CAMUNDA_BASE_URL;

  let authStrategy = (env.CAMUNDA_AUTH_STRATEGY ?? "").toUpperCase();
  if (!["NONE", "BASIC", "OAUTH"].includes(authStrategy)) {
    if (env.CAMUNDA_CLIENT_ID && env.CAMUNDA_CLIENT_SECRET) authStrategy = "OAUTH";
    else if (env.CAMUNDA_BASIC_AUTH_USERNAME && env.CAMUNDA_BASIC_AUTH_PASSWORD) authStrategy = "BASIC";
    else authStrategy = "NONE";
  }
  sdkConfig.CAMUNDA_AUTH_STRATEGY = authStrategy;
  // The SDK logs at info by default; we only want problems.
  sdkConfig.CAMUNDA_SDK_LOG_LEVEL ??= "warn";

  const which = (env.CAMUNDA_MCP_SERVERS ?? "cluster,processes")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  const endpoints: Endpoint[] = [];
  for (const name of which) {
    if (name !== "cluster" && name !== "processes") throw new Error(`CAMUNDA_MCP_SERVERS: unknown server "${name}" (use cluster, processes)`);
    const path = `/mcp/${name}`;
    endpoints.push({ name, path, url: new URL(`${baseUrl}${path}`) });
  }
  if (endpoints.length === 0) throw new Error("CAMUNDA_MCP_SERVERS is empty");

  const poll = Number(env.CAMUNDA_MCP_POLL_SECONDS ?? "30");
  const pollSeconds = Number.isFinite(poll) && poll >= 0 ? poll : 30;

  return { baseUrl, endpoints, pollSeconds, sdkConfig, authStrategy: authStrategy as ProxyConfig["authStrategy"] };
}
