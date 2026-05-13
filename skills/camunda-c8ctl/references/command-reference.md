# c8ctl Command Reference

Verb-and-resource matrix, resource aliases, common flags. For the full auto-generated reference (every flag of every command), see [the upstream docs](https://docs.camunda.io/docs/apis-tools/c8ctl/getting-started/) or run `c8ctl help <command>`.

## Command Structure

c8ctl uses a `<verb> <resource> [args] [flags]` shape:

```bash
c8ctl list pi                            # verb=list, resource=pi (process-instance)
c8ctl get pi 2251799813685249            # verb=get, resource=pi, key=...
c8ctl complete ut 2251799813685250       # verb=complete, resource=ut (user-task)
c8ctl search inc --state=ACTIVE          # verb=search, resource=inc (incident)
```

## Resource Aliases

| Alias | Resource |
|-------|----------|
| `pi` | `process-instance` |
| `pd` | `process-definition` |
| `ut` | `user-task` |
| `inc` | `incident` |
| `msg` | `message` |
| `var`, `vars` | `variable` |
| `auth` | `authorization` |
| `mr` | `mapping-rule` |

## Global Flags

These work on every command:

| Flag | Description |
|------|-------------|
| `--help`, `-h` | Show help |
| `--version`, `-v` | Show CLI version (or filter by process-definition version on supported commands) |
| `--profile <name>` | Use a specific profile for this command (overrides active profile) |
| `--dry-run` | Preview the API request without executing |
| `--verbose` | Show verbose output |
| `--fields <comma-separated>` | Restrict displayed columns / JSON fields |

## Search and List Flags

These work on `list` and `search` commands:

| Flag | Description |
|------|-------------|
| `--sortBy <field>` | Sort results by field |
| `--asc`, `--desc` | Sort direction |
| `--limit <n>` | Maximum number of results |
| `--all` | Disable pagination limit (list-only) |
| `--between <range>` | Date range filter (e.g., `7d`, `30d`, `2024-01-01..2024-12-31`) |
| `--dateField <field>` | Date field for `--between` filter |

`search` supports wildcard and case-insensitive variants of most filter flags. For example, `--name=foo` matches exactly; `--iname=foo*` is case-insensitive with a wildcard.

## Verb Catalog

Brief descriptions only. Use `c8ctl help <verb>` for resource-specific flags.

### Inspection

| Verb | Common usage |
|------|--------------|
| `get topology` | Cluster heartbeat: brokers, partitions, replication factor, version |
| `list pd` | Deployed process definitions |
| `list pi` | Running process instances |
| `list ut` | User tasks |
| `list inc` | Incidents |
| `list jobs` | Jobs (filter by `--type`, `--state`) |
| `list profiles` / `plugins` / `users` / `roles` / `groups` / `tenants` | Configuration resources |
| `search pd` / `pi` / `ut` / `inc` / `jobs` / `variables` | Search with wildcard and case-insensitive filters |
| `get pi <key> [--variables]` | Inspect one instance |
| `get inc <key>` | Inspect one incident |
| `get pd <key> [--xml]` | Inspect one process definition (use `--xml` to dump the BPMN) |

### Lifecycle (Process Instances)

| Verb | Common usage |
|------|--------------|
| `create pi --id=<bpmn-id> [--variables=...] [--awaitCompletion]` | Start a new process instance |
| `await pi --id=<bpmn-id>` | Shorthand for `create pi --awaitCompletion` (server-side wait) |
| `cancel pi <key>` | Cancel a running instance |
| `set pi <key> --variables=...` | Update variables on a running instance |

### User Tasks and Jobs

| Verb | Common usage |
|------|--------------|
| `complete ut <key> [--variables=...]` | Complete a user task |
| `assign ut <key> --assignee=<user>` | Assign a user task |
| `unassign ut <key>` | Unassign |
| `activate jobs <type> [--maxJobsToActivate=N] [--timeout=ms] [--worker=name]` | Activate jobs of a type |
| `complete job <key> [--variables=...]` | Complete a job |
| `fail job <key> [--retries=N] [--errorMessage=...]` | Fail a job |

### Messaging

| Verb | Common usage |
|------|--------------|
| `publish msg <name> [--correlationKey=...] [--variables=...]` | Publish a BPMN message |
| `correlate msg <name> [--correlationKey=...] [--variables=...]` | Publish and wait for correlation |

### Incidents

| Verb | Common usage |
|------|--------------|
| `resolve inc <key>` | Mark an incident as resolved (after fixing the root cause) |

### Deployment and Development

| Verb | Common usage |
|------|--------------|
| `deploy <file>` / `deploy <directory>` | Deploy BPMN/DMN/form resources |
| `run <file> [--variables=...]` | Deploy + start in a single step |
| `watch [--extensions=...]` | Auto-redeploy on file save |

### Profiles, Plugins, Output

| Verb | Common usage |
|------|--------------|
| `add profile <name> [flags]` | Create a c8ctl profile |
| `remove profile <name>` (alias `rm`) | Delete a c8ctl profile |
| `use profile <name>` / `which profile` | Switch / show active profile |
| `use tenant <id>` | Switch active tenant |
| `load plugin <pkg>` / `load plugin --from <url>` | Install a plugin |
| `unload plugin <pkg>` | Uninstall a plugin |
| `upgrade plugin <pkg> [<version>]` / `downgrade plugin <pkg> <version>` | Manage plugin versions |
| `sync plugin` | Reconcile installed plugins with the registry file |
| `init plugin <name>` | Scaffold a new plugin from template |
| `output [text\|json]` | Switch session output mode |
| `open <app>` | Open Operate / Tasklist / Modeler / Optimize in the browser |
| `completion <shell>` / `completion install` | Shell completion (bash, zsh, fish) |

## JSON Mode and AI / Scripting

For programmatic consumption, switch to JSON mode and combine with `--fields` for stable structured output:

```bash
c8ctl output json
c8ctl list pd --fields=key,bpmnProcessId,version,name
c8ctl get pi 2251799813685249 --variables --fields=key,state,variables
```

`--dry-run` shows what would be sent without executing — useful for previewing destructive operations before running them.

## Default File Extensions

`deploy`, `run`, and `watch` scan directories for these extensions by default:

`.bpmn`, `.dmn`, `.form`, `.md`, `.txt`, `.xml`, `.rpa`, `.json`, `.config`, `.yml`, `.yaml`

Override with `--extensions` (e.g., `--extensions=.bpmn,.dmn`).

## .c8ignore

Directory scans automatically ignore `node_modules/`, `target/`, `.git/`. Add a `.c8ignore` file with `.gitignore` syntax for project-specific patterns:

```gitignore
dist/
build/
**/draft-*.bpmn
!draft-approved.bpmn
```

## Building Blocks and Process Applications

Two folder conventions are recognized during deployment:

- **Building blocks** — folders containing `_bb-` in their name. Deployed first, marked with 🧱 in results.
- **Process applications** — folders containing a `.process-application` marker file. Marked with 📦 in results.

Building-block resources are listed first in deployment results, followed by process-application resources, then standalone resources.
