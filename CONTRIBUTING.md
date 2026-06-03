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

**Skills must be self-contained.** A skill directory is the unit of distribution — installers copy `skills/<name>/` into the consuming agent's skills path, and nothing else travels with it. `SKILL.md` and files under it may only reference paths inside their own skill directory or cross-reference other skills by name (see [SKILL.md Format](#skillmd-format)). Do not reach into sibling skills' `references/`/`scripts/`/`assets/`, and do not depend on any repo-level path. If two skills need the same asset, duplicate it or promote the shared content into a third skill that both cross-reference. This is what the [Agent Skills](https://agentskills.io) spec assumes, and it's why these skills work in Claude Code, Cursor, Copilot, Codex, Gemini CLI, and other compatible agents without modification.

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

## Linting

**Always run `make lint SKILL=<name>` after modifying a skill.** CI runs the same check on PRs touching `skills/` (`.github/workflows/lint.yml`) and will fail on hard violations.

```bash
make lint SKILL=camunda-feel        # check one skill (use after editing it)
make lint                           # check all skills
waza check <skill>                  # equivalent direct invocation
```

`waza check` covers: agentskills.io spec compliance (description length, required sections), token budget (per `.waza.yaml`), link health, frontmatter quality advisories. Returns non-zero on hard violations; warnings are advisory.

`waza` ships as an Azure Developer CLI (`azd`) extension, not a standalone binary. One-time install:

```bash
brew install azd
azd config set alpha.extensions on
azd ext source add -n waza -t url -l https://raw.githubusercontent.com/microsoft/waza/main/registry.json
azd ext install microsoft.azd.waza
```

After install, the `azd waza` command is on PATH and `make lint` works. The Makefile's "Install it from https://github.com/microsoft/waza" message refers to this extension flow, not a direct binary download.

## Evals

The `evals/` suite verifies skills *work* — the right skill loads for a prompt,
and the agent produces deployable, working artifacts. It's the behavioural gate
alongside `waza check` (lint), built on [Inspect AI](https://inspect.aisi.org.uk/).
Start at [`evals/README.md`](evals/README.md); the details live in three docs:

- [`evals/docs/concepts.md`](evals/docs/concepts.md) — the model: two kinds (trigger/outcome), two-phase sandbox, with/without-skill arms, the cost baseline
- [`evals/docs/runbook.md`](evals/docs/runbook.md) — run · interpret · add · maintain evals (for contributors and AI agents)
- [`evals/docs/ci.md`](evals/docs/ci.md) — labels, workflows, the PR comment, regenerating baselines, secrets

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

Follow [Conventional Commits](https://www.conventionalcommits.org/). Format: `<type>(<scope>): <subject>`. Scope is the skill name (`camunda-bpmn`, `camunda-feel`, …) or a repo-wide area (`ci`, `contributing`, `lint`, `repo`). Common types:

- `feat` — new skill or new capability within a skill
- `fix` — correction to existing skill content or tooling
- `docs` — **repo-level docs only**: README.md, AGENTS.md, CONTRIBUTING.md, issue/PR templates. *Not* for SKILL.md or `references/` edits
- `refactor` — restructuring without behavioural change (e.g., moving content into `references/`)
- `chore` — versioning, lint config, dependency bumps
- `test` — eval suites or test infrastructure

**`SKILL.md` and `references/` files are the product, not documentation.** Adding guidance, tightening wording, fixing an example, or restructuring a reference all change what the skill does — pick `feat` / `fix` / `refactor` based on the nature of the change. Reserve `docs` for the repo-level files listed above. When in doubt: if the change ships to skill consumers, it isn't `docs`.

Examples:

```
feat(camunda-dmn): add decision-table hit-policy reference
fix(camunda-connectors): correct sync caveat duplication
refactor(camunda-connectors): move post-apply concerns into references/
docs(contributing): document conventional commit format
docs(repo): require PR and issue templates in AGENTS.md
```

Wrong vs. right for skill content:

```
docs(camunda-bpmn): cover ad-hoc subprocess and end-event ioMapping   # ❌ ships new skill guidance
feat(camunda-bpmn): cover ad-hoc subprocess and end-event ioMapping   # ✅
```

Keep the subject under ~70 characters. Use the body for the *why*, not the *what*.

## Pull Request Process

1. Create a branch from `main`
2. Add/modify skills following the structure above
3. **Run `make lint SKILL=<name>` after every change** and fix any hard violations before pushing (CI runs the same check)
4. Use Conventional Commits (see above) for every commit on the branch
5. Submit a PR using the repo's [pull request template](.github/pull_request_template.md) as-is — don't substitute a custom shape. Issue templates live in `.github/ISSUE_TEMPLATE/`.
