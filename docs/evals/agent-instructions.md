# Eval suite — instructions for AI agents

For AI agents (Claude Code, Copilot CLI, Codex CLI) working on this
repo. Operational guide; concepts live in
[`concepts.md`](concepts.md); how-to lives in
[`scenarios.md`](scenarios.md).

## When to touch the eval suite

| Change you're making | Eval action |
|---|---|
| Editing a `skills/<X>/SKILL.md` or `references/` | If a scenario in `evals/scenarios/*` lists `X` in `metadata.skills`, run it locally and check the result before pushing. |
| Adding a new skill | Open a question: which failure mode would a scenario catch? If you have one, propose it. If you don't, **don't fabricate one** — leave evals untouched. |
| Lint-only changes (whitespace, link fixes, frontmatter) | Skip evals. `waza check` covers it. |
| Repo plumbing changes (`Makefile`, workflows, etc.) | Run `make eval SCENARIO=00-c8ctl-bootstrap` as a smoke test if your change could affect the harness. |
| Eval scenario / harness changes | Run the affected scenarios locally; update baselines per `scenarios.md` if intended. |

If in doubt, ask the user. Don't add a scenario speculatively. A
scenario without a concrete failure-mode hypothesis is dead weight —
it'll be ignored when it fails or be regenerated when it gets in the
way.

## How to run evals locally

Prerequisites: Docker, `uv` (installed via Astral; the harness will
auto-install dependencies via `uv sync`).

```bash
make eval SCENARIO=01-rocket-launch    # one scenario, ~1–2 min
make eval-all                          # all scenarios, ~15–20 min
make eval-baseline SCENARIO=<id>       # regenerate baseline.json
```

Logs land under `evals/logs/`. Open the trajectory viewer:

```bash
uv run inspect view evals/logs/
# http://localhost:7575
```

## How to interpret a failing eval

1. **Transcript first.** The `.eval` log shows every tool call, file
   read, and judge decision. If the agent didn't read the skill you
   expected, the prompt-or-trigger is the bug, not the skill content.
2. **Verifier second.** If the agent did the right thing but the
   verifier failed, reproduce the verifier outside the sandbox (see
   `scenarios.md § How to debug`).
3. **Flake check.** Re-run with `--epochs 3` before treating a single
   failure as a regression.
4. **Baseline diff.** `scripts/summarize.py` shows you what changed —
   pass-rate, token band, duration band. A scenario can pass but
   regress significantly on tokens; that's still a signal.

## Adding a scenario

Follow `scenarios.md § How to add a new scenario` exactly. Key
non-obvious rules:

- **Name the failure mode**, not the skill. `10-dmn-collect-ordering`,
  not `10-dmn-test`.
- **Start with `baseline.mode = "without-skill"`** unless the
  scenario is tool-shaped (transcript scorer asserting an MCP call
  fires). Mode `none` skips the comparison arm — only use it where the
  without-skill arm is logically meaningless.
- **Path-filter inclusion is automatic** via `metadata.skills` —
  don't hardcode the workflow matrix.
- **Edge cases are samples, not separate scenarios.** Add them as
  additional `Sample(id="edge-…", ...)` entries.

## Updating baselines after intentional behaviour change

```bash
make eval SCENARIO=<id>                # run to confirm the new behaviour
make eval-baseline SCENARIO=<id>       # rewrite baseline.json from last run
git diff evals/scenarios/<id>/baseline.json
# review every changed field — is the new pass-rate, token band, duration
# band actually what you intend? Or did you regress something you didn't
# mean to?
```

**Never** blanket-regen baselines. **Never** regen to "make CI green"
without diagnosing what changed.

## What NEVER to do

- ❌ **Don't pin baselines to current bad behaviour.** If pass-rate is
  0.4 and the skill is supposed to work, fix the skill — don't
  baseline 0.4.
- ❌ **Don't blanket-regen baselines.** Per-scenario, with diff review.
- ❌ **Don't add a scenario without justifying the baseline mode.** If
  you choose `mode: "none"` (skipping comparison), say in the PR
  description *why*.
- ❌ **Don't put scenario config in YAML sidecars.** The contract is
  `@task(metadata={...})` in `task.py`. One source.
- ❌ **Don't skip the without-skill arm** because "it makes the
  scenario slow". Slow scenarios go to nightly via
  `metadata.tier = "nightly"`.
- ❌ **Don't run evals on every commit.** Local iteration: one
  scenario at a time. CI handles the matrix.
- ❌ **Don't commit `.eval` logs.** They're CI artifacts, not source.
  `evals/logs/` is gitignored.

## Where the truth lives

- **What the suite is** → [`docs/plans/01-eval-suite.md`](../plans/01-eval-suite.md)
  (cross-PR coordination point; updated as PRs land)
- **Why** → [`concepts.md`](concepts.md)
- **How** → [`scenarios.md`](scenarios.md)
- **CI shape & PR comment** → [`ci-and-results.md`](ci-and-results.md)

If any of these disagree, the plan wins. Open a PR fixing the
discrepancy.
