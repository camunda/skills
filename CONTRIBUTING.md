# Contributing to Camunda Skills

## Skill Structure

Every skill is a directory under `skills/` containing at minimum a `SKILL.md` file:

```
skills/camunda-<name>/
├── SKILL.md              # Required — core instructions
├── references/           # Optional — detailed docs loaded on demand
├── scripts/              # Optional — executable code (non-interactive, version-pinned deps)
└── assets/               # Optional — templates, schemas, static resources
```

Eval cases for the skill live separately under `evals/camunda-<name>/`.

## SKILL.md Format

```yaml
---
name: camunda-<name>
description: What this skill does. Third person, max 1024 chars. Front-load the key use case.
---
```

Key rules:

- **Name must match directory name** (e.g., `camunda-bpmn` in `skills/camunda-bpmn/`)
- **Body under ~5000 words** — move detailed catalogs to `references/`
- **References one level deep** — no chains (SKILL.md → ref1.md → ref2.md)
- **Cross-reference other skills** by name when relevant
- **Tooling routes through c8ctl plugin commands** (e.g., `c8ctl bpmn lint`, `c8ctl element-template apply`, `c8ctl feel evaluate`) — c8ctl is a hard prerequisite for these skills

## Progressive Discovery

Skills use three tiers to manage context:

1. **Metadata** (~100 tokens) — always loaded (name + description from frontmatter)
2. **SKILL.md body** — loaded when skill activates
3. **References/scripts/assets** — loaded on demand when instructions reference them

Keep SKILL.md lean. If a section exceeds ~500 words of reference material, move it to `references/`.

## Evals

Every skill has an eval suite under `evals/camunda-<name>/`:

```
evals/camunda-<name>/
├── eval.yaml           # suite config (skill name, metrics, defaults)
├── tasks/*.yaml        # one task per file
├── graders/*.sh        # optional shell scripts for `program` graders
└── fixtures/           # optional input files for `inputs.files`
```

Three task patterns we use:

- **Trigger probes** — `expected.should_trigger` + a `trigger` grader. One YAML
  per case (positive or negative). Validates the skill's `description` triggers
  on the right prompts and stays silent on adjacent ones.
- **Quality tasks (LLM judge)** — `prompt` grader with a rubric. The judge
  scores the agent's output (or files written to `outputs/`) against
  explicit criteria. Good for prose answers and cross-cutting expectations.
- **Quality tasks (deterministic)** — `program` grader that shells to a
  script (e.g. `graders/feel-evaluate.sh`, `graders/bpmn-lint.sh`). The
  script reads the agent's output file from `$WAZA_WORKSPACE_DIR/outputs/`
  and exits 0 on pass, 1 on fail. Mix with the LLM judge in the same
  task to cover both behaviour and verifiable correctness.

A task with multiple graders passes only when all of them pass.

Run locally:

```bash
waza check <skill>                 # readiness check (schema, token budget, links)
waza run <skill>                   # full run
waza grade --output <results.json> # re-grade without re-running the agent
```

CI runs `waza run` on every PR that touches `evals/` or `skills/` and
uploads `eval-results` as an artifact (`.github/workflows/eval.yml`).

## Scripts

Scripts must be:
- **Non-interactive** — no TTY prompts or confirmation dialogs
- **Self-contained** — use inline dependency declarations or npx with version pinning
- **Idempotent** — safe to run multiple times

## Pull Request Process

1. Create a branch from `main`
2. Add/modify skills following the structure above
3. Ensure `waza check` passes for any skill you touched
4. Submit PR with description of changes
