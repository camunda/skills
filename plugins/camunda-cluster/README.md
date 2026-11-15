# camunda-cluster

Use a running Camunda 8 cluster from your AI agent: find incidents, inspect and start process instances, work user tasks, read variables, and call your deployed processes as tools.

The plugin connects two MCP servers that are built into the Orchestration Cluster (8.9+):

| Server | Endpoint | Tools |
|---|---|---|
| `camunda-cluster` | `/mcp/cluster` | Cluster status and topology; incidents (search, get, resolve); process definitions (search, get, XML); process instances (create, search, get); user tasks (search, get, assign, complete, variables); variables (search, get) |
| `camunda-processes` | `/mcp/processes` | One tool per deployed process with an MCP start event, plus `searchIncidents`, `getProcessInstance`, `searchVariables` |

Both are reached through [`c8ctl mcp-proxy`](https://docs.camunda.io/docs/apis-tools/orchestration-cluster-api-mcp/orchestration-cluster-api-mcp-setup/), a local stdio-to-HTTP proxy that authenticates with your c8ctl connection (OAuth client credentials or basic auth). Nothing to install beyond Node 20+: the plugin runs c8ctl with `npx`.

The plugin also ships a `camunda-cluster` skill that tells the agent how to use the tools safely (search before acting, confirm writes, eventual consistency, what still needs c8ctl).

## Choose the cluster

The proxy uses the same connection c8ctl would:

1. the active c8ctl profile: `c8ctl add profile …` then `c8ctl use profile <name>`;
2. otherwise `CAMUNDA_BASE_URL` and credentials (`CAMUNDA_CLIENT_ID`, `CAMUNDA_CLIENT_SECRET`, `CAMUNDA_OAUTH_URL`, `CAMUNDA_TOKEN_AUDIENCE`, or `CAMUNDA_USERNAME`/`CAMUNDA_PASSWORD`) in the environment the agent host starts from;
3. otherwise Camunda 8 Run on `http://localhost:8080`.

The MCP server is on by default in Camunda 8 Run and Docker Compose. On Helm add `camunda.mcp.enabled: true` to the orchestration `extraConfiguration`; on SaaS enable MCP support in the cluster's **Settings** tab. The proxy connects once at startup: after switching profile or starting the cluster, reconnect the MCP servers.

## Install

### Claude Code

```
/plugin marketplace add camunda/skills
/plugin install camunda-cluster@camunda-skills
```

### GitHub Copilot CLI

```
copilot plugin marketplace add camunda/skills
copilot plugin install camunda-cluster@camunda-skills
```

### OpenCode

Add to `opencode.json` (project) or `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "camunda-cluster": { "type": "local", "command": ["npx", "-y", "@camunda8/cli@^4.6.0", "mcp-proxy", "/mcp/cluster"] },
    "camunda-processes": { "type": "local", "command": ["npx", "-y", "@camunda8/cli@^4.6.0", "mcp-proxy", "/mcp/processes"] }
  }
}
```

### Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.camunda-cluster]
command = "npx"
args = ["-y", "@camunda8/cli@^4.6.0", "mcp-proxy", "/mcp/cluster"]

[mcp_servers.camunda-processes]
command = "npx"
args = ["-y", "@camunda8/cli@^4.6.0", "mcp-proxy", "/mcp/processes"]
```

### Claude Desktop, VS Code, others

Any MCP client that runs stdio servers: use the two `npx … mcp-proxy` commands above. Claude Desktop (`claude_desktop_config.json`) takes the same `mcpServers` block as this plugin's [`.mcp.json`](.mcp.json); if `npx` is not on the PATH that GUI apps see (nvm), use its absolute path.

For an unauthenticated local cluster, clients that support Streamable HTTP can also connect to `http://localhost:8080/mcp/cluster` directly, without the proxy.

## Not covered

The cluster MCP server has no tools for deploying, cancelling instances or publishing messages. Use c8ctl for those (the `camunda-process-mgmt` skill in the `camunda-skills` plugin).
