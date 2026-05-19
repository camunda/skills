# Contributing to Camunda Skills

## Reporting issues

- **Bug in a skill?** Open a [bug report](https://github.com/camunda/skills/issues/new?template=bug_report.yml). Including agent harness, model, OS, and `c8ctl` version helps a lot — skill behaviour varies across them.
- **Feature idea or new skill?** Open a [feature request](https://github.com/camunda/skills/issues/new?template=feature_request.yml).
- **General Camunda 8 question** not specific to a skill here? Ask on the [Camunda Forum](https://forum.camunda.io).
- **Issue with `c8ctl` itself** (not the skill wrapping it)? File it on [`camunda/c8ctl`](https://github.com/camunda/c8ctl/issues) — the skills route through c8ctl, so most CLI-layer bugs belong upstream.

## Skill Structure

Every skill is a directory under `skills/` containing at minimum a `SKILL.md` file:

```
skills/camunda-<name>/
├── SKILL.md              # Required — core instructions
├── references/           # Optional — detailed docs loaded on demand
├── scripts/              # Optional — executable code (non-interactive, version-pinned deps)
└── assets/               # Optional — templates, schemas, static resources
```

Eval suites are intentionally not checked in right now — see "Evals" below.

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
- **Cross-reference other skills** by name only — link to the skill (e.g. **camunda-c8ctl**), not into its `references/<file>.md`, and not to a named section of its `SKILL.md` (`§ "Safety: …"`). The target skill is the entry point; let it route the agent to the right reference. Make sure that target skill's own references list mentions the topic so it can be found after navigating in. **Do not inline-restate the target skill's rules or procedural details** in your cross-reference bullet — keep cross-ref bullets to a one-line topical pointer (`**camunda-X**: Use for …`). Deep-linking within your own skill's `references/` is fine — the constraint is cross-skill.
- **Tooling routes through c8ctl** (e.g., `c8ctl bpmn lint`, `c8ctl element-template apply`, `c8ctl feel evaluate`) — c8ctl is the programmatic API for these skills. If you find yourself reaching for a custom script, first check whether a c8ctl subcommand or plugin already does it; if not, prefer adding one upstream over baking shell glue into the skill.
- **Tag features introduced above the 8.8 floor** with their introduction version inline on first mention (e.g. `mockDmnDecision` *(8.9+)*, `COMPLETE_JOB_AD_HOC_SUB_PROCESS` *(8.9+)*). The repo's minimum is Camunda 8.8 — don't tag features that exist there, they're the baseline. Don't add per-skill version matrices either; tag only what actually landed later. Verify the introducing release via the [release notes](https://docs.camunda.io/docs/reference/announcements-release-notes/) or **camunda-docs** before writing the tag.

## Progressive Discovery

Skills use three tiers to manage context:

1. **Metadata** (~100 tokens) — always loaded (name + description from frontmatter)
2. **SKILL.md body** — loaded when skill activates
3. **References/scripts/assets** — loaded on demand when instructions reference them

Keep SKILL.md lean. If a section exceeds ~500 words of reference material, move it to `references/`.

## Evals

No eval suites are checked in right now. The waza migration replaced a custom
~5,200-line Python eval framework, and our first attempt at porting eval
content surfaced that the patterns we had didn't earn their cost yet:

- **Trigger probes** — we built `trigger_tests.yaml` for `camunda-feel` and
  observed precision/recall ~0% across positive prompts. The model has FEEL
  coverage in training and answers correctly without invoking the skill, even
  on non-trivial idiom questions. Trigger probes don't surface useful signal
  for utility skills whose subject matter is well-represented in training.
- **Quality tasks** — we ran the suite under `baseline: true` (with vs.
  without skills loaded). Delta was ~0 across all tasks. The Copilot SDK
  surfaces skill descriptions in routing context but the skill body only
  lands in context on explicit invocation, which the model declines for the
  same reason above.

The honest conclusion: until we have a concrete hypothesis about *what* an
eval should measure that `waza check` doesn't already prove (and that the
model can't fake from training), running expensive evals just produces noise.
We'll add suites back per-skill as we identify those hypotheses.

Linting is the enforcement bar for now:

```bash
make lint                    # waza check across all skills
make lint SKILL=camunda-feel # one skill
waza check <skill>           # direct invocation
```

CI runs `waza check` on every PR that touches `skills/`
(`.github/workflows/eval.yml`).

## Scripts

Prefer c8ctl over scripts. A `scripts/` directory is a last resort, not the
default — if you can express the same workflow as a c8ctl invocation (or a
plugin contributed upstream), do that instead. Custom scripts drift, hide
assumptions in shell, and split the surface an agent has to learn.

When a script is genuinely warranted, it must be:
- **Non-interactive** — no TTY prompts or confirmation dialogs
- **Self-contained** — use inline dependency declarations or npx with version pinning
- **Idempotent** — safe to run multiple times

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/). Format: `<type>(<scope>): <subject>`. Scope is the skill name (`camunda-bpmn`, `camunda-feel`, …) or a repo-wide area (`ci`, `contributing`, `lint`). Common types:

- `feat` — new skill or new capability within a skill
- `fix` — correction to existing skill content or tooling
- `docs` — README / CONTRIBUTING / AGENTS.md changes
- `refactor` — restructuring without behavioural change (e.g., moving content into `references/`)
- `chore` — versioning, lint config, dependency bumps
- `test` — eval suites or test infrastructure

Examples:

```
feat(camunda-dmn): add decision-table hit-policy reference
fix(camunda-connectors): correct sync caveat duplication
refactor(camunda-connectors): move post-apply concerns into references/
docs(contributing): document conventional commit format
```

Keep the subject under ~70 characters. Use the body for the *why*, not the *what*.

## Pull Request Process

1. Create a branch from `main`
2. Add/modify skills following the structure above
3. **Run `make lint SKILL=<name>` after every change** and fix any hard violations before pushing (CI runs the same check)
4. Use Conventional Commits (see above) for every commit on the branch
5. Submit PR with description of changes
