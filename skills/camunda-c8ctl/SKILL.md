---
name: camunda-c8ctl
description: |
  Use this skill to install, configure, and operate c8ctl (the Camunda 8 CLI), the foundation the other camunda-* skills build on.

  Use for: starting a local cluster via c8run, connecting to Camunda 8 SaaS or Self-Managed, managing connection profiles, installing c8ctl plugins, switching output to JSON for scripting, also when another camunda-* skill needs c8ctl and it isn't installed yet.

  Do not use for: writing BPMN (use camunda-bpmn), writing FEEL (use camunda-feel), or deploying and operating running processes (use camunda-process-mgmt — that skill builds on c8ctl).

  **Utility skill** — the foundation other camunda-* skills build on. Covers c8ctl cluster, c8ctl add/use profile, c8ctl load plugin.
---

# Camunda c8ctl CLI

Install and use [c8ctl](https://github.com/camunda/c8ctl) — the minimal-dependency CLI for Camunda 8.8+ — for connecting to clusters, deploying resources, and managing process automation. c8ctl is the foundation for the other camunda-* skills (`camunda-bpmn`, `camunda-connectors`, `camunda-feel`, `camunda-process-mgmt`, `camunda-ai-agent`).

## Prerequisites

- **Node.js ≥ 22.18.0** (required for native TypeScript support)

## Cross-References

- **camunda-bpmn**: Uses `c8ctl bpmn lint` (ships in c8ctl by default once [#347](https://github.com/camunda/c8ctl/pull/347) lands)
- **camunda-connectors**: Uses `c8ctl element-template search/info/get-properties/apply`
- **camunda-feel**: Uses `c8ctl feel evaluate`
- **camunda-process-mgmt**: Uses `c8ctl deploy`, `c8ctl run`, `c8ctl watch`, `c8ctl list pi`, `c8ctl search inc`, `c8ctl complete ut`, `c8ctl resolve inc`, etc.
- **camunda-ai-agent**: Uses `c8ctl element-template search/apply` to apply the AI Agent connector template

## Instructions

### Install

Install c8ctl globally from npm:

```bash
npm install -g @camunda8/cli
```

After installation, both `c8ctl` and the shorter alias `c8` are available. The other camunda-* skills use the `c8ctl` form for clarity.

Verify:

```bash
c8ctl --version
c8ctl help
```

### Verify default plugins (temporary — until camunda/c8ctl#347 lands)

The `bpmn`, `element-template`, and `feel` commands used by the other camunda-* skills are shipped as default plugins in [camunda/c8ctl#347](https://github.com/camunda/c8ctl/pull/347), which hasn't released yet. Verify each is available:

```bash
c8ctl bpmn --help              # camunda-bpmn
c8ctl element-template --help  # camunda-connectors, camunda-ai-agent
c8ctl feel --help              # camunda-feel
```

If any command exits non-zero, install c8ctl from the PR branch instead of the released npm package:

```bash
npm install -g github:camunda/c8ctl#feat/bpmn-apply-element-template-and-lint
```

**Remove this section once #347 is merged and released** — the plugins will then ship by default with `npm install -g @camunda8/cli`.

### Pick a Cluster

c8ctl needs a cluster to talk to. Before configuring a profile, **ask the user which cluster they want to use**:

1. **Local development cluster** (c8run) — recommended default for new projects, experiments, and local iteration. c8ctl can download, start, and manage c8run for you. See "Local Cluster" below.
2. **Camunda 8 SaaS** — managed cluster in Camunda's cloud. The user provides client credentials.
3. **Self-Managed** — a Camunda 8 cluster the user runs themselves (Kubernetes, Docker Compose, etc.). The user provides the base URL and (if secured) OAuth credentials.
4. **Camunda Modeler profile** — if the user has Camunda Desktop Modeler installed with a configured connection, c8ctl auto-imports those profiles. Use them with the `modeler:` prefix (e.g., `modeler:Local Dev`).

If the user hasn't decided and is doing local development, **suggest local c8run** — it has zero setup cost beyond `c8ctl cluster start`.

### Local Cluster (c8ctl cluster)

c8ctl ships with a default `cluster` plugin that wraps [c8run](https://docs.camunda.io/docs/self-managed/setup/deploy/local/c8run/). It downloads, starts, and stops a local Camunda 8 cluster for you.

```bash
# Start the latest stable release (downloads on first run)
c8ctl cluster start

# Start a specific minor version (rolling release — auto-updates patches)
c8ctl cluster start 8.9

# Start a specific full version
c8ctl cluster start 8.9.0-alpha5

# Use the alpha alias for the latest pre-release
c8ctl cluster start alpha

# Check status (running? what version? connection details?)
c8ctl cluster status

# Stream logs
c8ctl cluster logs

# Stop the cluster
c8ctl cluster stop
```

The cluster runs on `http://localhost:8080` by default. With no profile configured, c8ctl falls back to `http://localhost:8080/v2`, so most commands work out of the box against a freshly started local cluster.

For full c8ctl cluster command reference (list, install, list-remote, delete, cache locations, version aliases), see `references/local-cluster.md`.

### Connect: Profiles

Profiles store cluster connection details. Configure once, switch between clusters with one command.

```bash
# Minimal local profile (defaults to http://localhost:8080/v2)
c8ctl add profile local

# OAuth-secured cluster (SaaS or Self-Managed)
c8ctl add profile prod \
  --baseUrl=https://camunda.example.com \
  --clientId=your-client-id \
  --clientSecret=your-client-secret

# Switch the active profile
c8ctl use profile prod

# Show the current active profile
c8ctl which profile

# List all profiles (includes Camunda Modeler profiles with `modeler:` prefix)
c8ctl list profiles

# Use a Modeler profile
c8ctl use profile "modeler:Local Dev"

# One-off override for a single command (active profile unchanged)
c8ctl list pi --profile=staging
```

For full profile management — OAuth audience/endpoint, default tenants, multi-tenancy, Modeler integration locations, credential resolution order, environment variables — see `references/profiles.md`.

### Use the CLI

c8ctl follows a `<verb> <resource>` structure. Resources have short aliases (`pi` = process-instance, `pd` = process-definition, `ut` = user-task, `inc` = incident, `msg` = message).

Quick tour:

```bash
# Inspect the cluster
c8ctl get topology
c8ctl list pd                                  # deployed process definitions
c8ctl list pi                                  # running process instances
c8ctl search inc --state=ACTIVE                # active incidents

# Develop / deploy
c8ctl deploy ./process.bpmn                    # deploy a single resource
c8ctl deploy ./my-project                      # deploy a directory (supports _bb-* and .process-application)
c8ctl run ./order.bpmn --variables='{"orderId":"42"}'   # deploy + start in one step
c8ctl watch                                    # auto-redeploy on file save
c8ctl await pi --id=order-process              # block until completion

# Operate
c8ctl get pi 2251799813685249 --variables      # inspect an instance
c8ctl complete ut 2251799813685250 --variables='{"approved":true}'
c8ctl publish msg payment-received --correlationKey=order-42
c8ctl resolve inc 2251799813685251
c8ctl cancel pi 2251799813685249
```

For the full verb/resource matrix and resource-specific flags, see `references/command-reference.md`.

### Output Modes (for AI / scripting)

For AI-driven and scripted use, prefer JSON output and field selection:

```bash
# Switch the session to JSON output (persists across commands)
c8ctl output json

# Restrict columns (works in both text and JSON modes)
c8ctl list pd --fields=key,bpmnProcessId,version,name

# Preview an API request without executing it
c8ctl deploy ./process.bpmn --dry-run

# Pagination / sort (on list and search commands)
c8ctl list pi --limit=50 --sortBy=startDate --desc
```

When a skill produces commands intended for piping into `jq` or similar, set `c8ctl output json` first so structured fields are guaranteed.

### Plugins

c8ctl can be extended with npm packages that add commands. The `cluster` command is a default plugin shipped with c8ctl; `element-template`, `bpmn`, and `feel` ship as defaults once [#347](https://github.com/camunda/c8ctl/pull/347) lands (see "Verify default plugins" above for the temporary install). To add more:

```bash
# List installed plugins
c8ctl list plugins

# Load a plugin from npm
c8ctl load plugin <package-name>

# Load a plugin from a Git URL or local path
c8ctl load plugin --from https://github.com/camunda/c8ctl-plugin-diagram-renderer
c8ctl load plugin --from file:///path/to/local/plugin

# Upgrade / unload
c8ctl upgrade plugin <package-name>
c8ctl unload plugin <package-name>
```

For plugin lifecycle (init, sync, version pinning) and the storage layout, see `references/plugins.md`.

### Troubleshooting

- **`c8ctl: command not found`** (or `c8: command not found`) — npm's global bin directory isn't on `PATH`. Run `npm config get prefix` and add `<prefix>/bin` to `PATH`.
- **`Node.js version too old`** — c8ctl requires Node ≥ 22.18.0 for native TypeScript support. Use `nvm` or `asdf` to upgrade.
- **Local cluster won't start** — check `c8ctl cluster status` and `c8ctl cluster logs`. Common causes: port 8080 already in use, Java not installed (c8run needs JRE 21+), insufficient disk space for the binary download.
- **`c8ctl cluster start` reports "port 8080 in use" but the port is actually free** (`lsof`/`nc` show nothing listening) — you're likely running inside a sandboxed or otherwise restricted environment (some coding-agent harnesses, container modes with restricted networking, macOS App Sandbox, etc.) that blocks the underlying c8run from binding listen sockets. Run `c8ctl cluster start` directly on the user's machine outside any sandbox. If you're an AI coding agent operating in a restricted mode, escalate the command out of the sandbox or ask the user to run it themselves once; subsequent read-only commands against the running cluster usually work fine inside the sandbox.
- **OAuth errors against SaaS** — verify `--clientId`, `--clientSecret`, and (if your cluster requires it) `--audience` and `--oAuthUrl`. The cluster URL for SaaS is the *Zeebe REST address*, not the dashboard URL.

## References

For detailed reference material, read from `references/`:
- [local-cluster.md](references/local-cluster.md) — full `c8ctl cluster` command reference, version aliases (stable/alpha/rolling), cache locations
- [profiles.md](references/profiles.md) — profile management, OAuth flags, Modeler integration, tenant resolution, credential resolution order, environment variables
- [command-reference.md](references/command-reference.md) — verb/resource matrix, resource aliases, search flags, global flags
- [plugins.md](references/plugins.md) — plugin lifecycle, storage layout, building custom plugins
