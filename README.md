> [!NOTE]
> Technical preview. Skills are under heavy development and are subject to change.

# Camunda Skills

Official AI coding skills for Camunda 8 development. Build working Camunda solutions in minutes with AI guidance.

These skills use the [Agent Skills](https://agentskills.io) open standard. The package format is a skill directory containing `SKILL.md` with YAML frontmatter for `name` and `description`, plus optional skill-local references, scripts, and assets. The same package can be discovered by Claude Code, GitHub Copilot CLI, and other Agent Skills-compatible runtimes; command execution and credentials remain host capabilities.

## Available skills

| Skill | Description |
|-------|-------------|
| **camunda-c8ctl** | Install and configure c8ctl, set up a local cluster, manage profiles and plugins |
| **camunda-docs** | Look up the official Camunda 8 docs through the documented HTTP/MCP paths |
| **camunda-bpmn** | Create and edit BPMN 2.0 processes for Camunda 8/Zeebe |
| **camunda-feel** | Write and debug FEEL expressions |
| **camunda-dmn** | Author DMN decisions: decision tables, hit policies, literal expressions, and business-rule task wiring |
| **camunda-forms** | Create Camunda Form JSON schemas for user tasks |
| **camunda-connectors** | Browse and configure pre-built connectors through element templates |
| **camunda-development** | Choose between connectors, custom connector templates, and job workers before implementing an integration |
| **camunda-job-workers** | Implement job workers in Java, Camunda Spring Boot, or TypeScript |
| **camunda-connectors-development** | Build custom Camunda 8 connectors with a JSON template or the Connectors SDK |
| **camunda-process-mgmt** | Deploy resources, inspect instances, resolve incidents, and complete tasks through c8ctl |
| **camunda-process-test** | Author and run Camunda Process Test suites with full BPMN coverage |
| **camunda-ai-agents** | Build AI agents in BPMN with the AI Agent connector, tools, `fromAi()`, and prompts |

## Compatibility contract

The repository follows the [Agent Skills specification](https://agentskills.io/specification). The audit baseline is **2026-09-11**, recorded as `specRevisionOrAuditDate` in [`compatibility/audit.json`](compatibility/audit.json). The canonical repository contract is [`compatibility/portability-contract.md`](compatibility/portability-contract.md); it defines repository policy in addition to the external package format.

### Discovery and loading

1. A host discovers `skills/<name>/SKILL.md` and reads its `name` and `description` metadata.
2. The host loads the `SKILL.md` body when the skill is activated.
3. The host loads files under that skill directory on demand. Skills are self-contained; cross-skill references use the other skill's name rather than a repository path.
4. The host or adapter executes commands such as `c8ctl`, `dmnlint`, Maven, or Docker when the activated instructions require them.

`portability.json` is repository audit metadata, not additional `SKILL.md` frontmatter. The complete machine-readable inventory is [`compatibility/skills-index.json`](compatibility/skills-index.json). It and the dated audit must agree with every sidecar. Run `make compatibility-check` after changing a skill or its compatibility declaration; it reports one result per discovered skill and rejects missing or stale inventory paths.

### Harness guarantees

| Harness | Guarantee | Adapter boundary |
|---------|-----------|------------------|
| Claude Code | The standard skill package is discoverable through the Claude marketplace/plugin or a Claude skill path. Existing plugin and local-clone workflows remain supported. | c8ctl runs through the host terminal; `camunda-docs` may use its documented MCP path or bundled HTTP search script. |
| GitHub Copilot CLI | The Camunda plugin installs the same skill packages. Use `/plugin list` to verify the plugin, then invoke `camunda-bpmn` in a prompt to use the host terminal to create and lint a BPMN file. | Every current skill is `portable-with-adapter`: Copilot maps file editing, terminal commands, catalog access, SDKs, credentials, or MCP to its available tools. Tool names must not be assumed to be identical to another harness. |
| Generic Agent Skills-compatible runtime | The package format, metadata, discovery path, and skill-local files are portable. | The host must provide an installer or manual copy step and adapters for the commands, runtimes, credentials, and optional services used by a skill. |

No harness guarantee implies a Camunda cluster, credentials, a model provider, or a particular tool name. Those are explicit prerequisites below and in each sidecar.

### Skill portability status and local differences

This matrix is intentionally keyed to [`compatibility/skills-index.json`](compatibility/skills-index.json). Each row links to the authoritative sidecar; the linked sidecar contains the complete harness differences and limitations for that skill. Keep one row per inventory entry and update the row when the sidecar path or status changes.

| Skill | Status | Portability declaration | Local difference or limitation |
|-------|--------|-------------------------|--------------------------------|
| `camunda-ai-agents` | `portable-with-adapter` | [`portability.json`](skills/camunda-ai-agents/portability.json) | Copilot/generic hosts map connector-template application, file editing, model configuration, and tool execution. Live agent operations require c8ctl, a Camunda 8.8+ cluster, and a model-provider secret. |
| `camunda-bpmn` | `portable-with-adapter` | [`portability.json`](skills/camunda-bpmn/portability.json) | Copilot/generic hosts map BPMN editing and c8ctl commands. Linting requires c8ctl 3.0.0+; the documented format flow requires 3.2.0+ and a BPMN-aware workspace. |
| `camunda-c8ctl` | `portable-with-adapter` | [`portability.json`](skills/camunda-c8ctl/portability.json) | Hosts map terminal, profile, environment, and credential handling. Cluster/profile operations require c8ctl 3.0.0+ and Node.js 22.18.0+; remote-cluster operations require credentials, while local c8run uses its built-in no-auth `local` profile. |
| `camunda-connectors` | `portable-with-adapter` | [`portability.json`](skills/camunda-connectors/portability.json) | Hosts map element-template catalog access and BPMN editing. Basic operations require c8ctl 3.0.0+; engine-version discovery and FEEL `--set` behavior require 3.2.0+. |
| `camunda-connectors-development` | `portable-with-adapter` | [`portability.json`](skills/camunda-connectors-development/portability.json) | Hosts map c8ctl, Java/Maven, file edits, and connector runtime access. Java connector builds require Java 17+ and Maven 3.8+ or an equivalent toolchain. |
| `camunda-development` | `portable-with-adapter` | [`portability.json`](skills/camunda-development/portability.json) | The routing rules are portable, but the selected connector, worker, or cluster path needs the host's tools and runtime. |
| `camunda-dmn` | `portable-with-adapter` | [`portability.json`](skills/camunda-dmn/portability.json) | Hosts map DMN editing, `dmnlint`, c8ctl, and FEEL evaluation. Validation needs `dmnlint` plus a compatible FEEL or Camunda evaluation path. |
| `camunda-docs` | `portable-with-adapter` | [`portability.json`](skills/camunda-docs/portability.json) | MCP registration differs by harness; the bundled HTTP/Algolia script is the portable fallback. Network access to official docs or a current cache is required. |
| `camunda-feel` | `portable-with-adapter` | [`portability.json`](skills/camunda-feel/portability.json) | Hosts provide the FEEL engine, variables, and file adapters. The default c8ctl evaluation path requires a Camunda 8.9+ cluster; local and cluster engines can differ. |
| `camunda-forms` | `portable-with-adapter` | [`portability.json`](skills/camunda-forms/portability.json) | Hosts provide JSON editing/validation and optional c8ctl checks. Live form linking needs a Camunda 8.8+ BPMN project. |
| `camunda-job-workers` | `portable-with-adapter` | [`portability.json`](skills/camunda-job-workers/portability.json) | Hosts map source editing, SDK/build commands, and worker execution. Java/Spring targets need a reachable Camunda 8.8+ cluster; the orchestration TypeScript path requires 8.9+. |
| `camunda-process-mgmt` | `portable-with-adapter` | [`portability.json`](skills/camunda-process-mgmt/portability.json) | Hosts map c8ctl deployment and mutations to terminal and credentials. Live operations require an authorized Camunda 8.8+ cluster and explicit profile handling. |
| `camunda-process-test` | `portable-with-adapter` | [`portability.json`](skills/camunda-process-test/portability.json) | Hosts map Java, Maven, Docker, source editing, and reports. Tests require CPT 8.8+, Java 21+, Maven, and Docker; `.test.json` instructions require 8.9+. |

## Prerequisites and setup

### c8ctl and a Camunda cluster

Install the CLI and its default plugins:

```bash
npm install -g @camunda8/cli
c8ctl --version
c8ctl bpmn --help
c8ctl element-template --help
c8ctl feel --help
```

The c8ctl-based workflows require version 3.0.0 or newer. A local c8run cluster is the simplest credential-free development target:

```bash
c8ctl cluster start
c8ctl get topology --profile=local
```

The local profile uses `http://localhost:8080/v2`; pass `--profile=local` on cluster-touching commands. Local c8run also needs a JRE 21+ and enough disk space for the downloaded cluster. For SaaS or Self-Managed clusters, configure a profile once with [`c8ctl add profile`](https://docs.camunda.io/docs/apis-tools/c8ctl/getting-started/), then use an explicit `--profile=<name>`. Remote operations require an authorized Camunda 8.8+ cluster and credentials.

For CI or shells where a profile file is unsuitable, c8ctl can resolve standard `CAMUNDA_*` environment variables, including `CAMUNDA_BASE_URL`, `CAMUNDA_CLIENT_ID`, `CAMUNDA_CLIENT_SECRET`, and `CAMUNDA_DEFAULT_TENANT_ID`. Do not put real values in prompts, source files, or commits. Local connector secrets use `SECRET_<NAME>` environment variables loaded before `c8ctl cluster start`; keep the real secrets file out of version control. See the [c8ctl profile reference](skills/camunda-c8ctl/references/profiles.md) and [local-cluster reference](skills/camunda-c8ctl/references/local-cluster.md).

Not every operation needs a cluster. Reading or editing `SKILL.md`, BPMN/XML, DMN, and form files can be done locally. Linting and evaluation need the tool named by the skill; deployment, process operations, live agent workflows, and worker integration need a reachable cluster. `camunda-docs` needs network access to official documentation unless a current local cache is available. Harness-specific adapters are needed whenever the host does not expose the command, runtime, MCP client, or credential mechanism used by the skill.

### GitHub Copilot CLI

Prerequisites are a supported GitHub Copilot CLI installation and GitHub authentication. Workflows that use c8ctl require Node.js 22.18.0+; workflows that touch a Camunda cluster additionally require either a local cluster or an already configured remote profile. Install Copilot CLI using the [GitHub installation instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli), then register and install this plugin:

```bash
copilot plugin marketplace add camunda/skills
copilot plugin install camunda-skills@camunda
copilot plugin list
```

Start Copilot from the project directory with `copilot`. In the session, run `/plugin list` to verify the plugin, then invoke `camunda-bpmn` in your prompt. For a small useful example:

```text
Use camunda-bpmn to create a minimal Camunda 8 process in process.bpmn with a start event, one user task named "Review request", and an end event. Then run c8ctl bpmn lint process.bpmn and report the result.
```

Copilot may ask permission before editing files or running `c8ctl`; review those requests. The skill supplies the workflow, while Copilot supplies discovery, file editing, and terminal execution. The exact Copilot tool names are not part of the compatibility contract.

### Claude Code

The Claude marketplace/plugin path remains supported:

```bash
claude plugin marketplace add camunda/skills
claude plugin install camunda-skills@camunda-skills
```

For a local clone, copy a skill directory into the agent's skill lookup path, or load the full repository for a session:

```bash
git clone https://github.com/camunda/skills && cd skills
claude --plugin-dir .
# or, while developing this repository:
make try
```

### Generic installers and manual installation

Use the npm-based [Agent Skills installer](https://github.com/vercel-labs/skills) for a compatible host:

```bash
npx skills add camunda/skills --skill '*'
```

Or use GitHub CLI 2.90+ to install one skill for the current project or user scope:

```bash
gh skill install camunda/skills camunda-bpmn --agent <your-agent>
gh skill install camunda/skills camunda-bpmn --agent <your-agent> --scope user
```

Replace `<your-agent>` with an identifier supported by the host and run `gh skill install --help` for its current list. A manual installation is also valid: copy `skills/<skill-name>/` as a complete directory into the host's documented skill lookup path. Do not copy only `SKILL.md` when the skill has references, scripts, or assets. A generic host must translate the documented commands to its own tools and provide any required runtime, network, cluster, and credential adapters.

## Compatibility smoke checks

The checks themselves do not call a model, use credentials, or contact a live cluster. A clean
checkout still needs the `uv` executable, and the first `uv run` may create the environment and
download dependencies, so environment bootstrap can require network access:

```bash
make compatibility-check
```

It validates every skill's metadata, sidecar, inventory, audit date, and filesystem paths, then runs
the separate mock entry points `compatibility/adapters/mock-claude` and
`compatibility/adapters/mock-copilot`. Both entry points use the shared contract fixture: each
discovers `skills/camunda-bpmn/SKILL.md`, activates the fixed prompt, emits and validates
`process.bpmn`, and executes the exact command `c8ctl bpmn lint process.bpmn`. This verifies the
repository-defined adapter boundary, not harness-specific Claude or Copilot discovery, permission
prompts, or tool mapping; live integration is separate. A deterministic mock pass is required
evidence for the shared contract and is not independent product coverage.

Live Copilot smoke testing is not implemented in this repository yet. The compatibility workflow's `workflow_dispatch` runs deterministic mocks only and is not a live Copilot test. If live integration is added later, document its opt-in entry point and report `passed`, `failed`, `skipped`, or `unavailable`; `skipped` and `unavailable` never count as a deterministic mock pass.

## Quick start

1. Install c8ctl and start a local cluster:
   ```bash
   npm install -g @camunda8/cli
   c8ctl cluster start
   ```
2. Install the skill collection for [Copilot CLI](#github-copilot-cli), [Claude Code](#claude-code), or another compatible host.
3. Ask the agent to create and validate a BPMN process, or use the representative prompt above.
4. For live cluster work, inspect the active profile and pass an explicit profile to mutating commands.

Known limitations are recorded per skill in the [portability matrix](#skill-portability-status-and-local-differences) and its linked sidecar. In particular, MCP availability, model-provider credentials, c8ctl version, Java/Maven/Docker availability, and cluster access vary by host. No live integration is silently treated as available.

## Issues

Bug or feature request? [Open an issue](https://github.com/camunda/skills/issues/new/choose). General Camunda 8 questions belong on the [Camunda Forum](https://forum.camunda.io).

## License

Apache 2.0 - see [LICENSE](LICENSE).
