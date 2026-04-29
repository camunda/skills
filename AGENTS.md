# Camunda Skills

AI skills for Camunda 8.8+ development. Use these skills to create, deploy, and operate Camunda process automation solutions.

## Available Skills

| Skill | Use When |
|-------|----------|
| **camunda-bpmn** | Creating or editing BPMN 2.0 processes (elements, flows, gateways, events, subprocesses) |
| **camunda-feel** | Writing FEEL expressions (gateway conditions, input/output mappings, timer definitions) |
| **camunda-forms** | Creating Camunda Form JSON schemas for user tasks |
| **camunda-connectors** | Configuring pre-built connectors (REST, Slack, Kafka, etc.) via element templates |
| **camunda-deploy** | Deploying BPMN/DMN/form resources to a Camunda 8 cluster via c8ctl |
| **camunda-operate** | Monitoring process instances, resolving incidents, completing user tasks via c8ctl |

## c8ctl Setup

All cluster interaction uses [c8ctl](https://github.com/camunda/c8ctl). Configure a profile:

```bash
npm install -g @camunda8/cli
c8 add profile
```

Use JSON output mode for structured responses:

```bash
c8 output json
```

## Tooling

Skills use `npx` for tooling (auto-downloads, no install needed):

- **BPMN validation**: `npx -y bpmnlint@11 process.bpmn`
- **Element templates**: `npx -y element-templates-cli@0.5 --diagram in.bpmn --template template.json --element TaskId --output out.bpmn`

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
tools/            - Maintainer tooling (eval-viewer)
examples/         - Reference BPMN/form files
docs/             - c8ctl feature requests, design docs
evals/            - Eval workspace output (gitignored)
```

### Running Evals

Each skill has `evals/evals.json` with test prompts and assertions. Use the skill-creator eval framework (`/skill-creator`) to run evals:

1. Run eval prompts as subagent tasks (with-skill vs baseline)
2. Grade outputs against assertions
3. Review results in the eval viewer

Eval workspaces are written to `evals/<skill-name>/iteration-N/` (gitignored).

### Eval Viewer

Renders eval results with side-by-side BPMN diagrams and grading data:

```bash
cd tools/eval-viewer && npm install
node serve.js
```

Opens at http://localhost:3334. Auto-discovers all skills and iterations in `evals/`. Browse with the skill/iteration selectors at the top. Features:
- Side-by-side rendered BPMN/Form outputs (with_skill vs baseline)
- Pass/fail assertions with evidence
- Timing and token usage comparison
- Navigation across skills and iterations without restart

### Adding a New Skill

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide. In brief:

1. Create `skills/camunda-<name>/SKILL.md` with frontmatter (name, description)
2. Add `references/` for detailed docs, `scripts/` for tooling
3. Add `evals/evals.json` with 3-5 test cases
4. Run evals and iterate until quality is solid
