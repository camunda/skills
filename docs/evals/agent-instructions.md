# Eval suite — instructions for AI agents

For AI agents (Claude Code, Copilot CLI, Codex CLI) working on this
repo. Operational guide; concepts live in
[`concepts.md`](concepts.md); how-to lives in
[`scenarios.md`](scenarios.md).

## When to touch the eval suite

| Change you're making | Eval action |
|---|---|
| Editing a `skills/<X>/SKILL.md` or `references/` | If a result eval or scenario lists `X` in `metadata.skills` (or a trigger targets `X`), run it locally and check the result before pushing. |
| Adding a new skill | Open a question: which failure mode would an eval catch? If you have one, propose it. If you don't, **don't fabricate one** — leave evals untouched. |
| Lint-only changes (whitespace, link fixes, frontmatter) | Skip evals. `waza check` covers it. |
| Repo plumbing changes (`Makefile`, workflows, etc.) | Run `make eval-trigger SKILL=camunda-feel` as a smoke test if your change could affect the harness. |
| Eval / harness changes | Run the affected targets locally; update baselines per `scenarios.md` if intended. |

If in doubt, ask the user. Don't add an eval speculatively. An eval
without a concrete failure-mode hypothesis is dead weight — it'll be
ignored when it fails or be regenerated when it gets in the way.

## How to run evals locally

Prerequisites: Docker, `uv` (installed via Astral; the harness will
auto-install dependencies via `uv sync`).

```bash
make eval-trigger SKILL=camunda-feel      # one trigger eval
make eval-triggers                        # every trigger eval
make eval-result  SKILL=camunda-feel      # one per-skill result eval
make eval         SCENARIO=rocket-launch  # one cross-skill scenario
make eval-result  SKILL=camunda-feel ARM=without_skill   # comparison arm
make eval-baseline TARGET=<skill-or-scenario>            # regenerate baseline.json
```

Logs land under `evals/logs/`. Open the trajectory viewer:

```bash
make eval-viewer
# http://localhost:7575
```

## How to interpret a failing eval

1. **Transcript first.** The `.eval` log shows every tool call, file
   read, and judge decision. If the agent didn't read the skill you
   expected, the prompt-or-trigger is the bug, not the skill content.
2. **Scorer second.** If the agent did the right thing but a scorer
   failed, reproduce it outside the sandbox (see `scenarios.md §
   Debugging a failure`).
3. **Flake check.** Re-run with `--epochs 3` before treating a single
   failure as a regression.
4. **Baseline diff.** `scripts/summarize.py` shows whether a sample
   went over its token budget (`baseline × 1.5`). An eval can pass
   outcome but regress significantly on tokens; that's still a signal.

## Adding an eval

Follow `scenarios.md` exactly. Key non-obvious rules:

- **Name the failure mode**, not the skill (for scenarios:
  `dmn-collect-ordering`, not `dmn-test`).
- **A trigger is a `triggers.py`** at `evals/skills/<skill>/` — a `@task`
  that inlines `Positive`/`Negative` samples and calls `build_trigger_eval`;
  a result eval is a `task.py` with `METADATA` + `@task`.
- **Set `baseline.exclude`** to the load-bearing skill(s) so the
  `without_skill` arm measures what the skill adds.
- **Inclusion is automatic** via `metadata.skills` (the skill dir name for
  triggers) — don't hardcode the workflow matrix.
- **Edge cases are samples, not separate evals.** Add them as
  additional `Sample(id="edge-…", ...)` entries (or `Positive`/`Negative`
  entries for a trigger).

## Updating baselines after intentional behaviour change

```bash
make eval-result SKILL=<name>            # run to confirm the new behaviour
make eval-baseline TARGET=<name>         # rewrite baseline.json from last run
git diff evals/skills/<name>/baseline.json
# review the token counts — is the new budget what you intend, or did
# you regress something you didn't mean to?
```

**Never** blanket-regen baselines. **Never** regen to "make CI green"
without diagnosing what changed.

## What NEVER to do

- ❌ **Don't pin baselines to current bad behaviour.** Token counts
  only — the baseline is a cost ceiling, never the outcome bar. If the
  outcome is failing and the skill is supposed to work, fix the skill.
- ❌ **Don't blanket-regen baselines.** Per-target, with diff review.
- ❌ **Don't skip the `without_skill` arm** because "it makes the eval
  slow". The with-vs-without delta is the whole signal.
- ❌ **Don't run evals on every commit.** Local iteration: one target
  at a time. CI handles the matrix.
- ❌ **Don't commit `.eval` logs.** They're CI artifacts, not source.
  `evals/logs/` is gitignored.

## Where the truth lives

- **Why** → [`concepts.md`](concepts.md)
- **How** → [`scenarios.md`](scenarios.md)
- **CI shape & PR comment** → [`ci-and-results.md`](ci-and-results.md)
- **Design + roadmap (with divergences noted)** → [`../plans/01-eval-suite.md`](../plans/01-eval-suite.md)
  — for current state read its status box, not the body

If any of these disagree, the plan wins. Open a PR fixing the
discrepancy.
