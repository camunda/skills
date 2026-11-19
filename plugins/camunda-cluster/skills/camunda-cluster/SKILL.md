---
name: camunda-cluster
description: |
  Use when the user asks about what is happening on a running Camunda 8 cluster (incidents, stuck or running process instances, user tasks, variables, cluster health) or wants to act on it (resolve an incident, complete or assign a user task, start an instance, call a deployed process), and the camunda-cluster / camunda-processes MCP tools are available. Pairs with the camunda-process-mgmt skill, which covers the c8ctl equivalents and deployment.
---

# Camunda Cluster (MCP)

Two MCP servers on the Orchestration Cluster, each reached through `c8ctl mcp-proxy`. The proxy authenticates with the user's c8ctl connection, so the same credentials and permissions apply as for c8ctl and the REST API.

| Server | Endpoint | What it gives you |
|---|---|---|
| `camunda-cluster` | `/mcp/cluster` | Operational tools: `getClusterStatus`, `getTopology`, `searchIncidents` / `getIncident` / `resolveIncident`, `searchProcessDefinitions` / `getProcessDefinition` / `getProcessDefinitionXml`, `createProcessInstance` / `searchProcessInstances` / `getProcessInstance`, `searchUserTasks` / `getUserTask` / `assignUserTask` / `completeUserTask` / `searchUserTaskVariables`, `searchVariables` / `getVariable` |
| `camunda-processes` | `/mcp/processes` | One tool per deployed process that has an MCP start event (calling it starts an instance and returns its key), plus `searchIncidents`, `getProcessInstance`, `searchVariables` to follow it |

## Connecting

The proxy picks the cluster the same way c8ctl does:

1. The active c8ctl session profile (`c8ctl use profile <name>`).
2. Otherwise `CAMUNDA_BASE_URL` (plus `CAMUNDA_CLIENT_ID`/`CAMUNDA_CLIENT_SECRET`/`CAMUNDA_OAUTH_URL`/`CAMUNDA_TOKEN_AUDIENCE`, or `CAMUNDA_USERNAME`/`CAMUNDA_PASSWORD`) in the environment the agent host was started from.
3. Otherwise the `local` profile: Camunda 8 Run at `http://localhost:8080`.

If the tools are missing or fail to connect:

- Check the cluster is reachable: `c8ctl get topology`.
- The MCP server is on by default in Camunda 8 Run and Docker Compose. On Helm set `camunda.mcp.enabled: true`; on SaaS enable MCP support in the cluster's Settings tab (8.9+). A 404 on `/mcp/cluster` means it is off.
- After switching profile or starting the cluster, the user must reconnect the MCP servers (for example `/mcp` in Claude Code) — the proxy connects once at startup.

## Instructions

- **Read before you act.** Search first (`searchIncidents`, `searchProcessInstances`, `searchUserTasks`), show the user what you found, then act on keys from those results. Never invent keys.
- **Confirm writes.** `resolveIncident`, `completeUserTask`, `assignUserTask`, `createProcessInstance` and process tools change the cluster. State what you are about to do and with which key, unless the user already asked for exactly that action.
- **Resolve incidents properly.** Resolving only retries. Fix the cause first (deploy a fixed worker or model, or set the variable the expression needs) — see **camunda-process-mgmt**, *Resolving Incidents*.
- **Results are eventually consistent.** A search right after a write may not show it yet. Wait briefly and search again instead of repeating the write.
- **Variable values are serialized JSON.** Filter values in `searchUserTasks`/`searchVariables` are JSON strings (`"\"approved\""`); parse returned values before presenting them.
- **Deployed processes as tools.** Tools on `camunda-processes` appear only for processes deployed with an MCP start event, latest version only. They are listed when the server connects, so a process deployed during the session needs a reconnect.
- **Not here: deploying, cancelling, messages.** The cluster MCP server has no deploy, cancel or publish-message tools. Use c8ctl for those (**camunda-process-mgmt**), and **camunda-bpmn** to author and lint the model.
