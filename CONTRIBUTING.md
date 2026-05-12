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
- **Tooling routes through c8ctl plugin commands** (e.g., `c8 bpmn lint`, `c8 element-template apply`, `c8 feel evaluate`) — c8ctl is a hard prerequisite for these skills

## Progressive Discovery

Skills use three tiers to manage context:

1. **Metadata** (~100 tokens) — always loaded (name + description from frontmatter)
2. **SKILL.md body** (<5000 words) — loaded when skill activates
3. **References/scripts/assets** — loaded on demand when instructions reference them

Keep SKILL.md lean. If a section exceeds ~500 words of reference material, move it to `references/`.

## Evals

Every skill must have:

- `evals/evals.json` — quality cases (Tier 2). 3-5 entries with prose
  expectations and optional deterministic verifiers.
- `evals/triggers.json` — discovery probes (Tier 1). ~10 positive +
  ~10 negative cases the description should/shouldn't grab.
- `evals/baseline.json` — committed comparison point. Established by
  `make promote SKILL=<name>` after the first good iteration; re-bumped
  in dedicated PRs when the skill genuinely improves.

`evals.json` shape:

```json
{
  "skill_name": "camunda-<name>",
  "evals": [
    {
      "id": "discount-calculation",
      "prompt": "Write a FEEL expression... Write your final FEEL expression to outputs/answer.feel.",
      "expected_output": "Description for the LLM judge",
      "expectations": ["Use if-then-else", "Apply 0.15 as the discount rate"],
      "verifiers": [
        {"type": "feel-evaluate", "context": {"orderAmount": 1500}, "expected": 1275}
      ]
    }
  ]
}
```

Run locally:

```bash
make lint SKILL=camunda-<name>             # Tier 0
make eval SKILL=camunda-<name> RUNS=1      # cheap rehearsal
make eval SKILL=camunda-<name>             # full run (3 trials)
make compare SKILL=camunda-<name>          # diff vs committed baseline
make promote SKILL=camunda-<name>          # promote a clean iteration
```

For the full reference on tiers, artefacts, the runtime flow, the verifier
contract, and the lifecycle (bootstrap → iterate → promote → regress),
see [`docs/evals.md`](docs/evals.md). For a friendlier walkthrough of
the same concepts (with a plain-English unpack of the asymmetric
regression rule), open [`docs/evals-explained.html`](docs/evals-explained.html)
in a browser.

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
