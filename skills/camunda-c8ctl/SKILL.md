---
name: camunda-c8ctl
description: |
  Use this skill to install, configure, and operate c8ctl (the Camunda 8 CLI), the foundation the other camunda-* skills build on.

  Use for: starting a local cluster via c8run, connecting to Camunda 8 SaaS or Self-Managed via already-configured profiles, switching between connection profiles, installing c8ctl plugins, managing connector secrets for the local cluster, switching output to JSON for scripting, also when another camunda-* skill needs c8ctl and it isn't installed yet.

  Do not use for: writing BPMN (use camunda-bpmn), writing FEEL (use camunda-feel), or deploying and operating running processes (use camunda-process-mgmt — that skill builds on c8ctl).

  **Utility skill** — the foundation other camunda-* skills build on. Covers c8ctl cluster, c8ctl use profile, c8ctl load plugin.
---

# Camunda c8ctl CLI

Install and use [c8ctl](https://github.com/camunda/c8ctl) — the minimal-dependency CLI for Camunda 8.8+ — for connecting to clusters, deploying resources, and managing process automation. c8ctl is the foundation for the other camunda-* skills (`camunda-bpmn`, `camunda-connectors`, `camunda-feel`, `camunda-process-mgmt`, `camunda-ai-agent`).

## Prerequisites

- **Node.js ≥ 22.18.0** (required for native TypeScript support)

## Cross-References

- **camunda-bpmn**: Uses `c8ctl bpmn lint`
- **camunda-connectors**: Uses `c8ctl element-template search/info/get-properties/apply`
- **camunda-feel**: Uses `c8ctl feel evaluate`
- **camunda-process-mgmt**: Uses `c8ctl deploy`, `c8ctl run`, `c8ctl watch`, `c8ctl list pi`, `c8ctl search inc`, `c8ctl complete ut`, `c8ctl resolve inc`, etc.
- **camunda-ai-agent**: Uses `c8ctl element-template search/apply` to apply the AI Agent connector template

## Instructions

### Install

Install c8ctl globally from npm. The other camunda-* skills depend on the `bpmn`, `element-template`, and `feel` plugins, which require **c8ctl ≥ 3.0.0-alpha.1**. Pin the alpha explicitly — npm's `latest` tag still points at the 2.x line, which ships without these plugins:

```bash
npm install -g @camunda8/cli@3.0.0-alpha.1
```

After installation, both `c8ctl` and the shorter alias `c8` are available. The other camunda-* skills use the `c8ctl` form for clarity.

Verify:

```bash
c8ctl --version
c8ctl help
```

### Verify default plugins

The other camunda-* skills depend on three plugins that ship with c8ctl ≥ 3.0.0-alpha.1: `bpmn`, `element-template`, and `feel`. Verify each is available:

```bash
c8ctl bpmn --help              # camunda-bpmn
c8ctl element-template --help  # camunda-connectors, camunda-ai-agent
c8ctl feel --help              # camunda-feel
```

If any command exits non-zero, the installed c8ctl is older than 3.0.0-alpha.1 and lacks these plugins. **Ask the user to confirm before installing** — don't run the install unprompted — then run:

```bash
npm install -g @camunda8/cli@3.0.0-alpha.1
```

### Pick a Cluster

c8ctl needs a cluster to talk to. Before configuring a profile, **ask the user which cluster they want to use**:

1. **Local development cluster** (c8run) — recommended default for new projects, experiments, and local iteration. c8ctl can download, start, and manage c8run for you. See "Local Cluster" below.
2. **Camunda 8 SaaS** — managed cluster in Camunda's cloud. The user provides client credentials.
3. **Self-Managed** — a Camunda 8 cluster the user runs themselves (Kubernetes, Docker Compose, etc.). The user provides the base URL and (if secured) OAuth credentials.
4. **Camunda Modeler profile** — if the user has Camunda Desktop Modeler installed with a configured connection, c8ctl auto-imports those profiles. Use them with the `modeler:` prefix (e.g., `modeler:Local Dev`).

If the user hasn't decided and is doing local development, **suggest local c8run** — it has zero setup cost beyond `c8ctl cluster start`.

### Local Cluster (c8ctl cluster)

c8ctl ships with a default `cluster` plugin that wraps [c8run](https://docs.camunda.io/docs/self-managed/setup/deploy/local/c8run/). It downloads, starts, and stops a local Camunda 8 cluster for you.

**Examples**:

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

Profiles store cluster connection details. A `local` profile shipped with c8ctl already points at `http://localhost:8080/v2`, so no setup is needed for local c8run work — just pass `--profile=local`. Camunda Desktop Modeler profiles are auto-imported with a `modeler:` prefix.

For OAuth-secured clusters (SaaS or Self-Managed), profile setup is a one-time human task — see the [c8ctl docs](https://docs.camunda.io/docs/apis-tools/c8ctl/getting-started/) for `add profile` flags and credential handling. Don't run `add profile` on the agent's initiative; ask the user to configure profiles before using this skill.

Use already-configured profiles:

```bash
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

For multi-tenancy, credential resolution order, and Modeler integration details, see `references/profiles.md`.

### Safety: target the right cluster

c8ctl resolves cluster connections via the globally-active profile by default. That's risky: the active profile might still point at production or staging from a previous session, and a cluster-touching command will silently target it.

**Always pass `--profile=<name>` explicitly on commands that touch a cluster**, especially mutating ones (`deploy`, `run`, `cancel`, `resolve`, `complete`, `publish`, `watch`). Read-only commands (`get`, `list`, `search`, `feel evaluate`) are safer but the same discipline keeps the transcript auditable and prevents a forgotten `c8ctl use profile prod` from silently steering the next command.

Session opener: before doing any cluster-touching work, run `c8ctl which profile` and confirm with the user. If the active profile name suggests a shared environment (`prod`, `production`, `staging`, `live`, `saas`-prefixed, customer names), **ask before acting** — don't assume that profile is intended for the current work.

For new local-development projects, use `--profile=local` — don't inherit whatever profile a previous project left active.

`c8ctl cluster start/stop/status/logs` are unaffected: they operate on the local c8run process directly, not via a profile.

### Use the CLI

c8ctl has two command shapes:

- **Core API commands** follow `<verb> <resource>` — `list pi`, `get inc <key>`, `complete ut <key>`. Resources have short aliases (`pi` = process-instance, `pd` = process-definition, `ut` = user-task, `inc` = incident, `msg` = message).
- **Plugin commands** follow `<plugin> <subcommand>` — `cluster start`, `element-template apply`, `bpmn lint`, `feel evaluate`. The plugin name is the first token; subcommands are plugin-defined.

Quick tour (examples omit `--profile=<name>` for brevity — pass it explicitly per the Safety rule above):

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

For the full verb/resource matrix, plugin commands, and resource-specific flags, see `references/command-reference.md`.

### Output Modes (for AI / scripting)

For AI-driven and scripted use, request JSON per command and combine with `--fields` for stable structured output:

```bash
# Per-command JSON (deterministic, does not mutate session state)
c8ctl list pd --json --fields=key,bpmnProcessId,version,name

# Preview an API request without executing it
c8ctl deploy ./process.bpmn --dry-run

# Pagination / sort (on list and search commands)
c8ctl list pi --limit=50 --sortBy=startDate --desc
```

Prefer the per-invocation `--json` flag over `c8ctl output json` — the latter mutates `session.json` and leaks across other tools and sessions. The `C8CTL_OUTPUT_MODE=json` env var works for the current shell too, but shell state does not persist across separate tool calls in most agent harnesses, so an `export` in one step won't carry to the next. Always pass `--json` on the command itself when you need structured output.

### Plugins

c8ctl can be extended with npm packages that add commands. The `cluster`, `bpmn`, `element-template`, and `feel` commands are default plugins shipped with c8ctl. To add more:

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

For plugin lifecycle (init, sync, version pinning) and the storage layout, see [command-reference.md](references/command-reference.md) § Plugin Lifecycle.

### Troubleshooting

- **`c8ctl: command not found`** (or `c8: command not found`) — npm's global bin directory isn't on `PATH`. Run `npm config get prefix` and add `<prefix>/bin` to `PATH`.
- **`Node.js version too old`** — c8ctl requires Node ≥ 22.18.0 for native TypeScript support. Use `nvm` or `asdf` to upgrade.
- **Local cluster won't start** — check `c8ctl cluster status` and `c8ctl cluster logs`. Common causes: port 8080 already in use, Java not installed (c8run needs JRE 21+), insufficient disk space for the binary download.
- **`c8ctl cluster start` reports "port 8080 in use" but the port is actually free** (`lsof`/`nc` show nothing listening) — sandboxed environments that block socket binding (some coding-agent harnesses, restricted container modes, macOS App Sandbox) surface this way. Run `c8ctl cluster start` on the host directly.
- **c8ctl can't write to its default data directory** (sandboxed agents, restricted filesystems) — set `C8CTL_DATA_DIR=<writable-path>` before invoking c8ctl.
- **OAuth errors against SaaS** — verify the profile is configured correctly. The cluster URL for SaaS is the *Zeebe REST address*, not the dashboard URL. See the [c8ctl docs](https://docs.camunda.io/docs/apis-tools/c8ctl/getting-started/) for OAuth flags.

## References

For detailed reference material, read from `references/`:
- [local-cluster.md](references/local-cluster.md) — full `c8ctl cluster` command reference, version aliases (stable/alpha/rolling), cache locations, connector-secrets bootstrap flow
- [profiles.md](references/profiles.md) — profile management, OAuth flags, Modeler integration, tenant resolution, credential resolution order, environment variables
- [command-reference.md](references/command-reference.md) — verb/resource matrix, plugin command shape, resource aliases, search flags, global flags, and plugin lifecycle (install, upgrade, custom plugins)
