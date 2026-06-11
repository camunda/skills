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
| **camunda-ai-agents** | Building AI agents in BPMN — AI Agent connector on an ad-hoc subprocess, tool modeling, `fromAi()` parameters, prompts, sub-flow tools |

## Design goal: c8ctl is the programmatic API

[c8ctl](https://github.com/camunda/c8ctl) is the single programmatic surface for these skills — cluster operations, resource deployment, BPMN linting, element templates, FEEL evaluation all route through it. Skills should reach for a `c8ctl` subcommand or plugin before writing custom code. If a workflow currently needs a bespoke script, that's a signal a c8ctl command (or plugin) is missing — file it upstream rather than baking glue into a skill.

Why: c8ctl is versioned, tested, and shared across skills. Ad-hoc scripts drift, hide assumptions in shell, and split the surface area an agent has to learn. One CLI, consistent flags, structured (`--json`) output.

## c8ctl Setup (required)

c8ctl is a **hard prerequisite** for every skill below. The dedicated **camunda-c8ctl** skill walks through installation, picking a cluster (incl. starting a local one via `c8ctl cluster start`), profile setup, and plugin management.

Quick start. The `bpmn`, `element-template`, and `feel` plugins the skills below depend on require **c8ctl ≥ 3.0.0**. Install the latest version:

```bash
npm install -g @camunda8/cli
c8ctl cluster start         # spin up a local cluster (downloads c8run on first run)
c8ctl get topology --json   # confirm it's alive (use --json per command for scripting/AI use)
```

## Tooling

All skill tooling is unified under c8ctl plugin commands. `bpmn format`, `--engine-version` on discovery commands, and auto-`=` for FEEL `--set` require **c8ctl ≥ 3.2.0**; if a flag is unrecognised, prompt the user to upgrade: `npm install -g @camunda8/cli`.

- **BPMN validation**: `c8ctl bpmn lint process.bpmn` (auto-detects Camunda execution platform version; uses `.bpmnlintrc` if present)
- **BPMN canonicalization**: `c8ctl bpmn format [<file.bpmn>] [-i]` — round-trip through bpmn-moddle to normalize whitespace, attribute order, and element shapes (same pass as Modeler save); `-i` rewrites in place, default prints to stdout
- **Element templates** (run `c8ctl element-template sync` **once** before any OOTB-ID command; file/URL applies bypass the cache):
  - `c8ctl element-template search "<query>" [--limit N] [--engine-version <x.y.z>]` — discover OOTB connector templates; `--engine-version` filters to the latest version compatible with that engine (default limit 20)
  - `c8ctl element-template info <id> [--engine-version <x.y.z>]` — show metadata card (applies-to, engines, docs link); `--engine-version` resolves via engine-compatibility
  - `c8ctl element-template get-properties <id> [<name>...] [--engine-version <x.y.z>]` — list settable properties (condensed by default; supports glob filters and `--group <id>`); add `--detailed` for full per-property cards (Required, FEEL, Active when, Pattern); `--engine-version` resolves via engine-compatibility
  - `c8ctl element-template apply -i <template> <element-id> <bpmn> [--set key=value ...]` — apply a template (omit `-i` to print to stdout)
  - `c8ctl element-template get <id>` — print raw template JSON
  - `c8ctl element-template sync [--prune]` — refresh the local OOTB cache (required once before first use; re-run to pick up upstream changes)
- **FEEL evaluation**: `c8ctl feel evaluate '<expression>' [--var key=value | --vars '<json>']` — defaults to cluster evaluation (Scala FEEL engine; requires Camunda 8.9+). `--engine local` uses the `feelin` JS engine, which behaves DIFFERENTLY from the cluster engine — only use it when explicitly requested or the cluster is unreachable AND the user has confirmed.

## Conventions

- **File extensions**: `.bpmn` for processes, `.form` for Camunda Forms, `.dmn` for decision tables
- **BPMN naming**: Sentence case, tasks as "verb + object" (e.g., "Review invoice"), gateways as questions (e.g., "Amount exceeds limit?")
- **BPMN IDs**: Descriptive PascalCase (e.g., `ReviewInvoice`, `AmountExceedsLimit`)
- **Minimum version**: Camunda 8.8+
- **Version-tagged features**: Skill content tags features above the 8.8 floor with their introduction version inline (e.g. `*(8.9+)*`). Before recommending a tagged feature, check the user's cluster version against the tag; if the cluster version is unknown, ask. Untagged features are 8.8 baseline. When you're unsure whether an API exists at a given version, verify via **camunda-docs**.

---

## Maintaining this repo

Contributing to or maintaining the skills in this repo? See [CONTRIBUTING.md](CONTRIBUTING.md) for skill structure, the self-containment rule, cross-references, linting, evals, commit conventions, and the PR process.

**The skills have a behavioural eval suite (`evals/`), and it's meant to evolve with them.** When you add or change skill functionality, assess whether an eval should be added or adapted to cover it and raise it with the user — don't fabricate one where none earns its keep, but don't silently skip one that would catch a real failure mode. Evals are opt-in on CI and maintainer-gated by label: when a change warrants a run, the maintainer applies `evals:run` (skills the PR touches) or `evals:run-all` (whole suite) to the PR, or `evals:regenerate-baselines` after an intentional token-moving change. Surface this and suggest it — assume the user is a maintainer who can label — rather than waiting to be asked. Mechanics and the local loop: [evals/README.md](evals/README.md).
