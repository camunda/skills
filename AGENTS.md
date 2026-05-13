# Camunda Skills

AI skills for Camunda 8.8+ development. Use these skills to create, deploy, and operate Camunda process automation solutions.

## Available Skills

| Skill | Use When |
|-------|----------|
| **camunda-c8ctl** | Installing and configuring c8ctl, picking/setting up a cluster (incl. local c8run), managing profiles, plugins |
| **camunda-bpmn** | Creating or editing BPMN 2.0 processes (elements, flows, gateways, events, subprocesses) |
| **camunda-feel** | Writing FEEL expressions (gateway conditions, input/output mappings, timer definitions) |
| **camunda-forms** | Creating Camunda Form JSON schemas for user tasks |
| **camunda-connectors** | Configuring pre-built connectors (REST, Slack, Kafka, etc.) via element templates |
| **camunda-process-mgmt** | Deploying resources, starting/inspecting instances, resolving incidents, completing user tasks — all via c8ctl |
| **camunda-ai-agent** | Building AI agents in BPMN — AI Agent connector on an ad-hoc subprocess, tool modeling, `fromAi()` parameters, prompts, sub-flow tools |

## c8ctl Setup (required)

All cluster interaction and skill tooling uses [c8ctl](https://github.com/camunda/c8ctl). It is a **hard prerequisite** for the other skills. The dedicated **camunda-c8ctl** skill walks through installation, picking a cluster (incl. starting a local one via `c8ctl cluster start`), profile setup, and plugin management.

Quick start:

```bash
npm install -g @camunda8/cli
c8ctl cluster start         # spin up a local cluster (downloads c8run on first run)
c8ctl get topology          # confirm it's alive
c8ctl output json           # switch to structured output for scripting/AI use
```

## Tooling

All skill tooling is unified under c8ctl plugin commands:

- **BPMN validation**: `c8ctl bpmn lint process.bpmn` (auto-detects Camunda execution platform version; uses `.bpmnlintrc` if present)
- **Element templates**:
  - `c8ctl element-template search "<query>" [--limit N]` — discover OOTB connector templates (default limit 20)
  - `c8ctl element-template info <id>` — show metadata card (applies-to, engines, docs link)
  - `c8ctl element-template get-properties <id> [<name>...]` — list settable properties (condensed by default; supports glob filters and `--group <id>`); add `--detailed` for full per-property cards (Required, FEEL, Active when, Pattern)
  - `c8ctl element-template apply -i <template> <element-id> <bpmn> [--set key=value ...]` — apply a template (omit `-i` to print to stdout)
  - `c8ctl element-template get <id>` — print raw template JSON
  - `c8ctl element-template sync [--prune]` — refresh the local OOTB cache
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
evals/            - Eval suites (one per skill)
  <skill>/
    eval.yaml       - Suite config (skill, metrics, defaults)
    tasks/*.yaml    - One task per file (trigger probes + quality cases)
    graders/*.sh    - Optional shell scripts shelled to by `program` graders
    fixtures/       - Optional input files referenced by tasks via `inputs.files`
examples/         - Reference BPMN/form files
.waza.yaml        - Project-wide waza config
.github/workflows - CI: runs `waza run` on PRs touching evals/ or skills/
```

### Running Evals

Evals run via [waza](https://github.com/microsoft/waza). Install once with the Azure
Developer CLI extension (see `.github/workflows/eval.yml`) or `go install
github.com/microsoft/waza`.

```bash
waza check                          # readiness check (token budget, link health, schema, eval suite)
waza check <skill>                  # one skill only
waza run                            # run all suites
waza run <skill>                    # run one skill's suite
waza grade --output <results.json>  # re-grade existing results without re-running the agent
waza dev <skill>                    # interactive frontmatter improvement loop
```

Per-run results land in `results/<timestamp>/<model>.json`. The CI workflow
uploads them as `eval-results` artifacts on every PR.

### Adding a New Skill

See [CONTRIBUTING.md](CONTRIBUTING.md). The eval-side recipe:

1. `waza new skill <name>` (or hand-create `skills/<name>/SKILL.md`).
2. Add a suite under `evals/<name>/` — copy `evals/camunda-feel/` as a
   reference (it has both trigger probes and quality tasks with `program`
   graders).
3. `waza check <name>` to validate schema + advisory checks.
4. `waza run <name>` for a cheap rehearsal.
