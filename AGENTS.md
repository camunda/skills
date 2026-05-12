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

## c8ctl Setup (required)

All cluster interaction and skill tooling uses [c8ctl](https://github.com/camunda/c8ctl). It is a **hard prerequisite** for the other skills. The dedicated **camunda-c8ctl** skill walks through installation, picking a cluster (incl. starting a local one via `c8 cluster start`), profile setup, and plugin management.

Quick start:

```bash
npm install -g @camunda8/cli
c8 cluster start         # spin up a local cluster (downloads c8run on first run)
c8 get topology          # confirm it's alive
c8 output json           # switch to structured output for scripting/AI use
```

## Tooling

All skill tooling is unified under c8ctl plugin commands:

- **BPMN validation**: `c8 bpmn lint process.bpmn` (auto-detects Camunda execution platform version; uses `.bpmnlintrc` if present)
- **Element templates**:
  - `c8 element-template search "<query>" [--limit N]` — discover OOTB connector templates (default limit 20)
  - `c8 element-template info <id>` — show metadata card (applies-to, engines, docs link)
  - `c8 element-template get-properties <id> [<name>...]` — list settable properties (condensed by default; supports glob filters and `--group <id>`); add `--detailed` for full per-property cards (Required, FEEL, Active when, Pattern)
  - `c8 element-template apply -i <template> <element-id> <bpmn> [--set key=value ...]` — apply a template (omit `-i` to print to stdout)
  - `c8 element-template get <id>` — print raw template JSON
  - `c8 element-template sync [--prune]` — refresh the local OOTB cache
- **FEEL evaluation**: `c8 feel evaluate '<expression>' [--var key=value | --vars '<json>']` — defaults to cluster evaluation (Scala FEEL engine; requires Camunda 8.9+). `--engine local` uses the `feelin` JS engine, which behaves DIFFERENTLY from the cluster engine — only use it when explicitly requested or the cluster is unreachable AND the user has confirmed.

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
skills/           - Skill definitions (each skill = SKILL.md + references/ + evals/)
tools/
  skill-lint/     - Tier-0 structural + schema lint
  eval-runner/    - Tier-1/2 harness (subprocess to anthropics/skills' run_eval.py
                    for triggers; claude-agent-sdk + grader.md for quality;
                    pluggable verifiers)
  external/       - SHA-pinned upstream clones (gitignored, recreated by
                    `make setup-skill-creator`)
examples/         - Reference BPMN/form files
docs/             - Reference docs and design notes
  evals.md          ← read this first for the eval framework
evals/            - Per-run iteration outputs (gitignored)
```

### Running Evals

```bash
make lint                           # Tier 0, all skills
make lint SKILL=camunda-feel        # Tier 0, one skill
make setup-skill-creator            # one-time: clone the SHA-pinned upstream
make eval SKILL=camunda-feel RUNS=1 # cheap rehearsal
make eval SKILL=camunda-feel        # full run (3 trials)
make compare SKILL=camunda-feel     # diff vs committed baseline (markdown via --format markdown)
make promote SKILL=camunda-feel     # write the new baseline.json
```

Per-run iterations land at `evals/<skill>/iteration-N/`. Each one ships
with a self-contained `report.html` (open via `file://`) and an
`index.html` at `evals/<skill>/` that lists all iterations with their
headline metrics.

For the full picture — three-tier model, verifiers, the
bootstrap/iterate/promote/regress lifecycle, cost discipline, and how
to add evals for a new skill — see [`docs/evals.md`](docs/evals.md).
A plain-English overview of the same concepts (including a friendlier
unpack of the asymmetric regression rule) lives at
[`docs/evals-explained.html`](docs/evals-explained.html); open in a
browser. Harness internals (SDK contract, SHA-pin update procedure)
are in [`tools/eval-runner/AGENTS.md`](tools/eval-runner/AGENTS.md).

### Adding a New Skill

See [CONTRIBUTING.md](CONTRIBUTING.md) for the high-level checklist and
[`docs/evals.md`](docs/evals.md) for the eval-side recipe (lint →
triggers.json → evals.json with verifiers → cheap rehearsal →
promote).
