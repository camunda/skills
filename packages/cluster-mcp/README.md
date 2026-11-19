# @camunda8/cluster-mcp

A local MCP server (stdio) for a Camunda 8.9+ Orchestration Cluster. It connects to the cluster's built-in MCP servers and gives an AI agent (Claude Desktop, Claude Code, Copilot, Codex, Cursor, …) one set of tools:

- **`/mcp/cluster`**: operations tools: cluster status and topology, process definitions and instances, incidents, user tasks, variables.
- **`/mcp/processes`**: one tool per deployed process that has an MCP start event; calling it starts an instance. The tool is named after `io.camunda.tool:name` (`greet`), without the `_<subscription key>` suffix the cluster adds, so it keeps its name when the process is redeployed.
- **`camunda_process_tools`** and **`camunda_call_process_tool`**: list the process tools deployed right now and start one by name. Some hosts read the tool list only once per session: Claude Desktop answers `list_changed` by re-reading the list, but doesn't pass the new tools to the chat. Through these two tools the agent can still reach processes deployed during the conversation.
- **`camunda_connection_status`**: a local tool that reports the address, the auth strategy and, for each cluster server, whether it is reachable and the last error. The agent uses it when tools are missing.

Compared with connecting to the cluster endpoints directly, it adds:

- **Authentication** through the Camunda SDK: OAuth client credentials (SaaS, Self-Managed with Identity), basic auth (C8 Run with auth on) or none. Tokens are cached and refreshed, and a 401 triggers one refresh and retry.
- **Processes deployed mid-session.** The cluster's servers are stateless and don't announce changes. This server re-reads the tool list every 30 s and sends `notifications/tools/list_changed` when it changes, so a newly deployed process shows up without reconnecting in hosts that honour it (for the others, see `camunda_call_process_tool`). Requests time out after 30 s, so a hung cluster can't stall the polling.
- **One server instead of two.** The two tool lists are merged; `/mcp/processes` repeats three operations tools (`searchIncidents`, `getProcessInstance`, `searchVariables`) and the `/mcp/cluster` versions are kept.
- The cluster servers' instructions are passed on to the agent.
- A cluster that is down at startup does not stop the server; it keeps retrying.

## Install

### Claude Desktop

Download `camunda-cluster-<version>.mcpb` from the [releases](https://github.com/camunda/skills/releases) and open it. Claude Desktop shows a form for the cluster address and credentials; secrets are stored in the OS keychain.

### Any MCP client (npx)

```json
{
  "mcpServers": {
    "camunda-cluster": {
      "command": "npx",
      "args": ["-y", "@camunda8/cluster-mcp@0"],
      "env": {
        "CAMUNDA_REST_ADDRESS": "https://bru-2.zeebe.camunda.io/<cluster-id>",
        "CAMUNDA_CLIENT_ID": "<client id>",
        "CAMUNDA_CLIENT_SECRET": "<client secret>"
      }
    }
  }
}
```

For a local C8 Run without auth, no `env` is needed: the default address is `http://localhost:8080`.

## Configuration

The standard Camunda SDK environment variables, so an existing SDK `.env` works as is:

| Variable | Meaning |
|---|---|
| `CAMUNDA_REST_ADDRESS` | Cluster REST address, with or without `/v2`. Default `http://localhost:8080`. `CAMUNDA_BASE_URL` (c8ctl's name) is accepted too |
| `CAMUNDA_AUTH_STRATEGY` | `NONE`, `BASIC` or `OAUTH`. When unset: `OAUTH` if a client id and secret are set, `BASIC` if a username and password are set, otherwise `NONE` |
| `CAMUNDA_CLIENT_ID`, `CAMUNDA_CLIENT_SECRET` | OAuth client credentials |
| `CAMUNDA_OAUTH_URL` | Token endpoint (SDK default: Camunda SaaS) |
| `CAMUNDA_TOKEN_AUDIENCE`, `CAMUNDA_OAUTH_SCOPE` | Token audience and scope, when your identity provider needs them |
| `CAMUNDA_BASIC_AUTH_USERNAME`, `CAMUNDA_BASIC_AUTH_PASSWORD` | Basic auth |
| `CAMUNDA_MCP_SERVERS` | Which cluster servers to use: `cluster`, `processes` or both (default `cluster,processes`) |
| `CAMUNDA_MCP_POLL_SECONDS` | How often to re-read the tool list (default 30, `0` turns polling off) |

Other SDK variables (mTLS, `CAMUNDA_OAUTH_CACHE_DIR`, `CAMUNDA_SDK_LOG_LEVEL`, …) are passed to the SDK unchanged. Logs go to stderr.

## Requirements

- Camunda 8.9 or later, with the MCP gateway enabled. A 404 on `/mcp/cluster` means it is off; `camunda_connection_status` says so.
- Node.js 20 or later (Claude Desktop brings its own).

## Develop

```sh
npm install
npm run build    # type-check + bundle to dist/index.js
npm run smoke    # end-to-end against a fake cluster (OAuth, basic, list_changed, routing)
npm run pack:mcpb
```
