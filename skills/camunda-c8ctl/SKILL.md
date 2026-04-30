---
name: camunda-c8ctl
description: Installs, configures, and uses c8ctl (the Camunda 8 CLI). This skill should be used when the user mentions c8ctl, c8, the Camunda CLI, needs to connect to a Camunda 8 cluster, set up a local cluster for development, manage cluster profiles, or run cluster operations from the terminal. Also use this skill when other Camunda skills require c8ctl and it isn't installed or configured yet.
---

# Camunda c8ctl CLI

Install and use [c8ctl](https://github.com/camunda/c8ctl) — the minimal-dependency CLI for Camunda 8.8+ — for connecting to clusters, deploying resources, and managing process automation. c8ctl is the foundation for the other camunda-* skills (`camunda-bpmn`, `camunda-connectors`, `camunda-feel`, `camunda-deploy`, `camunda-operate`).

## Prerequisites

- **Node.js ≥ 22.18.0** (required for native TypeScript support)

## Cross-References

- **camunda-bpmn**: Uses `c8 bpmn lint` (ships in c8ctl by default)
- **camunda-connectors**: Uses `c8 element-template search/info/get-properties/apply`
- **camunda-feel**: Uses `c8 feel evaluate`
- **camunda-deploy**: Uses `c8 deploy`, `c8 run`, `c8 watch`
- **camunda-operate**: Uses `c8 list pi`, `c8 search inc`, `c8 complete ut`, `c8 resolve inc`, etc.

## Instructions

### Install

Install c8ctl globally from npm:

```bash
npm install -g @camunda8/cli
```

After installation, both `c8ctl` and the shorter alias `c8` are available.

Verify:

```bash
c8 --version
c8 help
```

### Pick a Cluster

c8ctl needs a cluster to talk to. Before configuring a profile, **ask the user which cluster they want to use**:

1. **Local development cluster** (c8run) — recommended default for new projects, experiments, and local iteration. c8ctl can download, start, and manage c8run for you. See "Local Cluster" below.
2. **Camunda 8 SaaS** — managed cluster in Camunda's cloud. The user provides client credentials.
3. **Self-Managed** — a Camunda 8 cluster the user runs themselves (Kubernetes, Docker Compose, etc.). The user provides the base URL and (if secured) OAuth credentials.
4. **Camunda Modeler profile** — if the user has Camunda Desktop Modeler installed with a configured connection, c8ctl auto-imports those profiles. Use them with the `modeler:` prefix (e.g., `modeler:Local Dev`).

If the user hasn't decided and is doing local development, **suggest local c8run** — it has zero setup cost beyond `c8 cluster start`.

### Local Cluster (c8 cluster)

c8ctl ships with a default `cluster` plugin that wraps [c8run](https://docs.camunda.io/docs/self-managed/setup/deploy/local/c8run/). It downloads, starts, and stops a local Camunda 8 cluster for you.

```bash
# Start the latest stable release (downloads on first run)
c8 cluster start

# Start a specific minor version (rolling release — auto-updates patches)
c8 cluster start 8.9

# Start a specific full version
c8 cluster start 8.9.0-alpha5

# Use the alpha alias for the latest pre-release
c8 cluster start alpha

# Check status (running? what version? connection details?)
c8 cluster status

# Stream logs
c8 cluster logs

# Stop the cluster
c8 cluster stop
```

The cluster runs on `http://localhost:8080` by default. With no profile configured, c8ctl falls back to `http://localhost:8080/v2`, so most commands work out of the box against a freshly started local cluster.

For full c8 cluster command reference (list, install, list-remote, delete, cache locations, version aliases), see `references/local-cluster.md`.

### Connect: Profiles

Profiles store cluster connection details. Configure once, switch between clusters with one command.

```bash
# Minimal local profile (defaults to http://localhost:8080/v2)
c8 add profile local

# OAuth-secured cluster (SaaS or Self-Managed)
c8 add profile prod \
  --baseUrl=https://camunda.example.com \
  --clientId=your-client-id \
  --clientSecret=your-client-secret

# Switch the active profile
c8 use profile prod

# Show the current active profile
c8 which profile

# List all profiles (includes Camunda Modeler profiles with `modeler:` prefix)
c8 list profiles

# Use a Modeler profile
c8 use profile "modeler:Local Dev"

# One-off override for a single command (active profile unchanged)
c8 list pi --profile=staging
```

For full profile management — OAuth audience/endpoint, default tenants, multi-tenancy, Modeler integration locations, credential resolution order, environment variables — see `references/profiles.md`.

### Use the CLI

c8ctl follows a `<verb> <resource>` structure. Resources have short aliases (`pi` = process-instance, `pd` = process-definition, `ut` = user-task, `inc` = incident, `msg` = message).

Quick tour:

```bash
# Inspect the cluster
c8 get topology
c8 list pd                                  # deployed process definitions
c8 list pi                                  # running process instances
c8 search inc --state=ACTIVE                # active incidents

# Develop / deploy
c8 deploy ./process.bpmn                    # deploy a single resource
c8 deploy ./my-project                      # deploy a directory (supports _bb-* and .process-application)
c8 run ./order.bpmn --variables='{"orderId":"42"}'   # deploy + start in one step
c8 watch                                    # auto-redeploy on file save
c8 await pi --id=order-process              # block until completion

# Operate
c8 get pi 2251799813685249 --variables      # inspect an instance
c8 complete ut 2251799813685250 --variables='{"approved":true}'
c8 publish msg payment-received --correlationKey=order-42
c8 resolve inc 2251799813685251
c8 cancel pi 2251799813685249
```

For the full verb/resource matrix and resource-specific flags, see `references/command-reference.md`.

### Output Modes (for AI / scripting)

For AI-driven and scripted use, prefer JSON output and field selection:

```bash
# Switch the session to JSON output (persists across commands)
c8 output json

# Restrict columns (works in both text and JSON modes)
c8 list pd --fields=key,bpmnProcessId,version,name

# Preview an API request without executing it
c8 deploy ./process.bpmn --dry-run

# Pagination / sort (on list and search commands)
c8 list pi --limit=50 --sortBy=startDate --desc
```

When a skill produces commands intended for piping into `jq` or similar, set `c8 output json` first so structured fields are guaranteed.

### Plugins

c8ctl can be extended with npm packages that add commands. The `element-template`, `bpmn`, `feel`, and `cluster` commands used by the other camunda-* skills are all default plugins — already installed and ready to use. To add more:

```bash
# List installed plugins
c8 list plugins

# Load a plugin from npm
c8 load plugin <package-name>

# Load a plugin from a Git URL or local path
c8 load plugin --from https://github.com/camunda/c8ctl-plugin-diagram-renderer
c8 load plugin --from file:///path/to/local/plugin

# Upgrade / unload
c8 upgrade plugin <package-name>
c8 unload plugin <package-name>
```

For plugin lifecycle (init, sync, version pinning) and the storage layout, see `references/plugins.md`.

### Troubleshooting

- **`c8: command not found`** — npm's global bin directory isn't on `PATH`. Run `npm config get prefix` and add `<prefix>/bin` to `PATH`.
- **`Node.js version too old`** — c8ctl requires Node ≥ 22.18.0 for native TypeScript support. Use `nvm` or `asdf` to upgrade.
- **Local cluster won't start** — check `c8 cluster status` and `c8 cluster logs`. Common causes: port 8080 already in use, Java not installed (c8run needs JRE 21+), insufficient disk space for the binary download.
- **OAuth errors against SaaS** — verify `--clientId`, `--clientSecret`, and (if your cluster requires it) `--audience` and `--oAuthUrl`. The cluster URL for SaaS is the *Zeebe REST address*, not the dashboard URL.

## References

For detailed reference material, read from `references/`:
- `references/local-cluster.md` — full `c8 cluster` command reference, version aliases (stable/alpha/rolling), cache locations
- `references/profiles.md` — profile management, OAuth flags, Modeler integration, tenant resolution, credential resolution order, environment variables
- `references/command-reference.md` — verb/resource matrix, resource aliases, search flags, global flags
- `references/plugins.md` — plugin lifecycle, storage layout, building custom plugins
