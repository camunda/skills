# Contributing to Camunda Skills

## Skill Structure

Every skill is a directory under `skills/` containing at minimum a `SKILL.md` file:

```
skills/camunda-<name>/
├── SKILL.md              # Required — core instructions (<5000 words)
├── references/           # Optional — detailed docs loaded on demand
├── scripts/              # Optional — executable code (non-interactive, version-pinned deps)
├── assets/               # Optional — templates, schemas, static resources
└── evals/                # Required — eval cases for quality assurance
    └── evals.json
```

## SKILL.md Format

```yaml
---
name: camunda-<name>
description: What this skill does. Third person, max 1024 chars. Front-load the key use case.
---
```

The body follows the template in the plan. Key rules:

- **Name must match directory name** (e.g., `camunda-bpmn` in `skills/camunda-bpmn/`)
- **Body under 5000 words** — move detailed catalogs to `references/`
- **References one level deep** — no chains (SKILL.md -> ref1.md -> ref2.md)
- **Cross-reference other skills** by name when relevant
- **Tools use `npx` with version pinning** (e.g., `npx -y bpmnlint@11`)

## Progressive Discovery

Skills use three tiers to manage context:

1. **Metadata** (~100 tokens) — always loaded (name + description from frontmatter)
2. **SKILL.md body** (<5000 words) — loaded when skill activates
3. **References/scripts/assets** — loaded on demand when instructions reference them

Keep SKILL.md lean. If a section exceeds ~500 words of reference material, move it to `references/`.

## Evals

Every skill must have `evals/evals.json` with 3-5 eval cases:

```json
{
  "skill_name": "camunda-<name>",
  "evals": [
    {
      "id": 1,
      "prompt": "User prompt that triggers the skill",
      "expected_output": "Description of expected result",
      "expectations": [
        "The output includes X",
        "The output is valid Y"
      ]
    }
  ]
}
```

Run evals using the skill-creator eval framework.

## Scripts

Scripts must be:
- **Non-interactive** — no TTY prompts or confirmation dialogs
- **Self-contained** — use inline dependency declarations or npx with version pinning
- **Idempotent** — safe to run multiple times

## Pull Request Process

1. Create a branch from `main`
2. Add/modify skills following the structure above
3. Ensure all evals pass
4. Submit PR with description of changes
