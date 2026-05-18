# Camunda Skills

AI skills for Camunda 8.8+ development. Use these skills to create, deploy, and operate Camunda process automation solutions.

## Available Skills

| Skill | Use When |
|-------|----------|
| **camunda-c8ctl** | Installing and configuring c8ctl, picking/setting up a cluster (incl. local c8run), managing profiles, plugins |
| **camunda-docs** | Verifying a Camunda 8 technical fact against the official docs (FEEL signatures, BPMN extension shapes, API endpoints, version requirements) before writing it down |
| **camunda-bpmn** | Creating or editing BPMN 2.0 processes (elements, flows, gateways, events, subprocesses) |
| **camunda-feel** | Writing FEEL expressions (gateway conditions, input/output mappings, timer definitions) |
| **camunda-dmn** | Authoring DMN decisions for business-rule tasks — decision tables (UNIQUE/ANY/FIRST/RULE ORDER/COLLECT), literal expressions, DRG linking, structural validation via `npx dmnlint` |
| **camunda-forms** | Creating Camunda Form JSON schemas for user tasks |
| **camunda-connectors** | Configuring pre-built connectors (REST, Slack, Kafka, etc.) via element templates |
| **camunda-development** | Choosing between OOTB connectors, custom connector templates, custom Java connectors, and job workers before writing integration code |
| **camunda-job-workers** | Implementing custom Camunda 8 job workers in Java, Camunda Spring Boot, or TypeScript — handler code that activates jobs and signals complete / fail / BPMN error |
| **camunda-connectors-development** | Building custom Camunda 8 connectors — JSON-only template on a protocol connector (Path A) or custom Java connector via the Connectors SDK (Path B, outbound + inbound) |
| **camunda-process-mgmt** | Deploying resources, starting/inspecting instances, resolving incidents, completing user tasks — all via c8ctl |
| **camunda-process-test** | Authoring and running Camunda Process Test (CPT) suites that reach 100% BPMN coverage with segment-based scenarios — `.test.json` instructions, `mvn test`, coverage report parsing |
| **camunda-ai-agent** | Building AI agents in BPMN — AI Agent connector on an ad-hoc subprocess, tool modeling, `fromAi()` parameters, prompts, sub-flow tools |

## Design goal: c8ctl is the programmatic API

[c8ctl](https://github.com/camunda/c8ctl) is the single programmatic surface for these skills — cluster operations, resource deployment, BPMN linting, element templates, FEEL evaluation all route through it. Skills should reach for a `c8ctl` subcommand or plugin before writing custom code. If a workflow currently needs a bespoke script, that's a signal a c8ctl command (or plugin) is missing — file it upstream rather than baking glue into a skill.

Why: c8ctl is versioned, tested, and shared across skills. Ad-hoc scripts drift, hide assumptions in shell, and split the surface area an agent has to learn. One CLI, consistent flags, structured (`--json`) output.

## c8ctl Setup (required)

c8ctl is a **hard prerequisite** for every skill below. The dedicated **camunda-c8ctl** skill walks through installation, picking a cluster (incl. starting a local one via `c8ctl cluster start`), profile setup, and plugin management.

Quick start. The `bpmn`, `element-template`, and `feel` plugins the skills below depend on require **c8ctl ≥ 3.0.0-alpha.1** — pin the alpha explicitly, since npm's `latest` still points at 2.x:

```bash
npm install -g @camunda8/cli@3.0.0-alpha.1
c8ctl cluster start         # spin up a local cluster (downloads c8run on first run)
c8ctl get topology --json   # confirm it's alive (use --json per command for scripting/AI use)
```

## Tooling

All skill tooling is unified under c8ctl plugin commands:

- **BPMN validation**: `c8ctl bpmn lint process.bpmn` (auto-detects Camunda execution platform version; uses `.bpmnlintrc` if present)
- **Element templates** (run `c8ctl element-template sync` **once** before any OOTB-ID command; file/URL applies bypass the cache):
  - `c8ctl element-template search "<query>" [--limit N]` — discover OOTB connector templates (default limit 20)
  - `c8ctl element-template info <id>` — show metadata card (applies-to, engines, docs link)
  - `c8ctl element-template get-properties <id> [<name>...]` — list settable properties (condensed by default; supports glob filters and `--group <id>`); add `--detailed` for full per-property cards (Required, FEEL, Active when, Pattern)
  - `c8ctl element-template apply -i <template> <element-id> <bpmn> [--set key=value ...]` — apply a template (omit `-i` to print to stdout)
  - `c8ctl element-template get <id>` — print raw template JSON
  - `c8ctl element-template sync [--prune]` — refresh the local OOTB cache (required once before first use; re-run to pick up upstream changes)
- **FEEL evaluation**: `c8ctl feel evaluate '<expression>' [--var key=value | --vars '<json>']` — defaults to cluster evaluation (Scala FEEL engine; requires Camunda 8.9+). `--engine local` uses the `feelin` JS engine, which behaves DIFFERENTLY from the cluster engine — only use it when explicitly requested or the cluster is unreachable AND the user has confirmed.

## Conventions

- **File extensions**: `.bpmn` for processes, `.form` for Camunda Forms, `.dmn` for decision tables
- **BPMN naming**: Sentence case, tasks as "verb + object" (e.g., "Review invoice"), gateways as questions (e.g., "Amount exceeds limit?")
- **BPMN IDs**: Descriptive PascalCase (e.g., `ReviewInvoice`, `AmountExceedsLimit`)
- **Minimum version**: Camunda 8.8+

---

## For Skill Maintainers

The sections below are for developers maintaining this skills repository.

### Repository Structure

```
skills/           - Skill definitions (each skill = SKILL.md + references/)
examples/         - Reference BPMN/form files
.waza.yaml        - Project-wide waza config (token limits, defaults)
.github/workflows/lint.yml - CI: runs `waza check` on PRs touching skills/
```

No eval suites are checked in right now. They were removed in the waza migration
once we learned that trigger probes don't fire for utility skills the model
knows from training (precision/recall ~0% on camunda-feel), and quality-task
delta against the with-vs-without-skills baseline is ~0 because the skill body
only loads on explicit invocation. We'll add evals back deliberately, per skill,
once we have a hypothesis about what to measure that the linter can't already
prove. Until then, `waza check` is the enforcement bar.

### Linting

**Always run `make lint SKILL=<name>` after modifying a skill.** CI runs the same check on PRs touching `skills/` and will fail on hard violations.

```bash
make lint SKILL=camunda-feel        # check one skill (use after editing it)
make lint                           # check all skills
waza check <skill>                  # equivalent direct invocation
```

`waza check` covers: agentskills.io spec compliance (description length, required
sections), token budget (per `.waza.yaml`), link health, frontmatter quality
advisories. Returns non-zero on hard violations; warnings are advisory.

`waza` ships as an Azure Developer CLI (`azd`) extension, not a standalone binary.
One-time install:

```bash
brew install azd
azd config set alpha.extensions on
azd ext source add -n waza -t url -l https://raw.githubusercontent.com/microsoft/waza/main/registry.json
azd ext install microsoft.azd.waza
```

After install, the `azd waza` command is on PATH and `make lint` works. The
Makefile's "Install it from https://github.com/microsoft/waza" message refers
to this extension flow, not a direct binary download.

### Adding a New Skill

See [CONTRIBUTING.md](CONTRIBUTING.md). Hand-create `skills/<name>/SKILL.md` and
its `references/`, then run `make lint SKILL=<name>` until clean.

### Cross-References Between Skills

Cross-reference other skills by name only (`**camunda-X**`). No section anchors
(`§ "…"`), no links into another skill's `references/`, no inline-restating of
the target skill's rules. Keep cross-ref bullets to a one-line topical pointer
(`**camunda-X**: Use for …`). See [CONTRIBUTING.md § SKILL.md Format](CONTRIBUTING.md#skillmd-format).

### Commits

Use [Conventional Commits](https://www.conventionalcommits.org/) — `<type>(<scope>): <subject>`,
with the skill name as the scope (e.g. `feat(camunda-dmn): …`, `fix(camunda-bpmn): …`).
See [CONTRIBUTING.md § Commit Messages](CONTRIBUTING.md#commit-messages) for the full list of types and examples.
