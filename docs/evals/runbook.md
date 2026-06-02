# Eval suite — local runbook

Day-to-day loop for running and reading evals on your machine. For the "why"
(sandbox model, baseline semantics) see [`concepts.md`](concepts.md); for
authoring a new eval see [`scenarios.md`](scenarios.md).

## Command cheatsheet

| Command | Does |
|---|---|
| `make eval-images` | Build the Docker sandbox images (one-time; outcome evals only) |
| `make eval-triggers` | Run **all** trigger evals |
| `make eval-triggers SKILL=camunda-feel` | Run **one** skill's trigger eval |
| `make eval-outcomes TARGET=skills/camunda-feel` | Run **one** outcome eval (a `skills/` or `scenarios/` dir) |
| `make eval-outcomes TARGET=scenarios/rocket-launch ARM=without_skill` | …the comparison arm |
| `make eval-outcomes` | Run the **whole** outcome suite (slow + costly) |
| `make eval-viewer` | Open the trajectory viewer over `evals/logs` (`localhost:7575`) |
| `uv run evals-pass-fail` | Gate verdict for the **latest** log (pass a path for a specific one) |
| `make eval-baseline TARGET=skills/camunda-feel` | Rewrite that eval's `outcomes_baseline.json` from its last run |
| `uv run evals-list` | List every target + the skills it covers |

**Creds:** the default model is `anthropic/claude-sonnet-4-6` — `export
ANTHROPIC_API_KEY`. For another provider pass `MODEL=…` plus that provider's
creds (e.g. CI's Bedrock model:
`MODEL=anthropic/bedrock/global.anthropic.claude-sonnet-4-6` with AWS creds in
the environment).

## Two kinds

| | Trigger | Outcome |
|---|---|---|
| Asks | does the right skill load? | does the agent reach the right result? |
| Runs | one structured-output call, **no sandbox** | agent in a **Docker sandbox** (maybe a live cluster) |
| Speed/cost | ~3s, ~10–15k tokens | minutes, ~100k–300k tokens |
| Arms | single (`with_skill` only) | `with_skill` / `without_skill` |
| Baseline | none | `outcomes_baseline.json` |

## Interpreting a trigger

Two gating scorers (both must hit **1.0**):

- **`skill_loaded`** — of the samples that assert a *must-load*, were they all
  routed to? `<1.0` ⇒ the skill's description isn't winning prompts it should.
- **`skill_not_loaded`** — of the samples that assert a *must-stay-out*, did the
  forbidden skills stay out? `<1.0` ⇒ the skill (or a sibling) over-triggers,
  **or** the guard is too strict.

`mean` is over *samples that have that assertion*, so e.g. `skill_not_loaded =
0.500` with 2 negatives = exactly one failed. Ignore `stderr` at these sample
counts — read the per-sample explanation instead.

**Find the failing sample** → `make eval-viewer` (the sample scored 0), or:

```bash
uv run evals-pass-fail   # latest log: per-sample pass/fail + the routed-skills explanation
```

**The lever is the skill *description*.** Triggers route purely off the
`<available_skills>` catalog (name + SKILL.md frontmatter `description`). Edit the
description, re-run `make eval-triggers SKILL=<name>`, watch the number. If the
routing is actually fine and the *assertion* is wrong, relax the sample in
`triggers.py` instead.

## Interpreting an outcome

Scorers are either **gating** (the verdict) or **diagnostic** (shown, never gates):

- Gating: the judge (`model_graded_qa`) and/or deterministic checks
  (`feel_evaluates_to`, `bpmn_lint_clean`, `process_deployed_on_cluster`,
  `cpt_scorer`).
- Diagnostic: `assert_skill_loaded(..., gating=False)` — did the agent actually
  read the skill.

```bash
uv run evals-pass-fail   # PASS/FAIL per sample: gating scorers + token budget
make eval-viewer         # the transcript — every tool call, file read, judge note
```

Two independent signals: **outcome** (did gating scorers pass) and **cost**
(tokens vs baseline — next section).

## Baseline (cost only, never the quality bar)

`outcomes_baseline.json` stores each sample's observed **tokens per arm**. The
gate fails a sample whose tokens exceed **baseline × 1.5** — an upper ceiling,
nothing else. Outcome correctness is gated by the *scorers*, never the baseline.

```bash
make eval-outcomes TARGET=skills/camunda-feel        # produce a fresh run
make eval-baseline TARGET=skills/camunda-feel        # rewrite the baseline from it
git diff evals/skills/camunda-feel/outcomes_baseline.json   # review before committing
```

- Regenerate only after an **intentional** behaviour change (review the token
  diff — is the new budget what you meant?).
- **Never** blanket-regen, and never to "make it green."
- Adding a new sample never breaks others — a new id has no entry until you regen.
- Triggers have no baseline.

## with_skill / without_skill

```bash
make eval-outcomes TARGET=skills/camunda-feel                      # with_skill (default)
make eval-outcomes TARGET=skills/camunda-feel ARM=without_skill    # comparison
```

- `with_skill` exposes every skill. `without_skill` **disables** the load-bearing
  skill(s) named in the eval's `METADATA.baseline.exclude`; all other skills stay
  available.
- The question is *"what does this skill add"* — the **delta** on the gating
  scorers is the signal:
  - loads + better result ⇒ the skill helps.
  - skill removed + still-good result ⇒ it isn't pulling its weight.
- `without_skill` is a **comparison, not a bar** — its cost gate is skipped.
- Triggers can't do this (you can't measure "the right skill loads" with it removed).

## The loop

1. Edit a skill (`SKILL.md` body, or its frontmatter `description` for routing).
2. **Routing changed?** `make eval-triggers SKILL=<name>`.
3. **Behaviour changed?** `make eval-outcomes TARGET=skills/<name>` (add
   `ARM=without_skill` to see the delta).
4. Red? `make eval-viewer` → drill the failing sample.
5. Behaviour intentionally changed *and* tokens moved? `make eval-baseline
   TARGET=…` + review the diff.

## Gotchas

- Triggers need no Docker/cluster; outcomes need `make eval-images` first and
  Docker running.
- Run `make lint` outside any command sandbox (it hits `docs.camunda.io` for
  link health).
- Run `uv run ruff format .` (from `evals/`) before committing Python changes.
