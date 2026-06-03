# Eval suite — concepts

The "why" and the mental model behind `evals/`. To run or add an eval see
[`runbook.md`](runbook.md); for CI and the PR comment see [`ci.md`](ci.md).

## What this checks (and how it relates to lint)

Two complementary gates guard the skills, answering different questions:

- **`waza check`** (lint) — is a skill *well-formed*? Spec compliance, token
  budget, frontmatter quality, link health. Fast, runs on every PR.
- **Eval suite** (this) — does a skill *work*? Does the right skill load for a
  prompt, and does the agent produce a deployable, working artifact (BPMN that
  lints + deploys, FEEL that evaluates, a CPT test that passes)?

Evals are built on [Inspect AI](https://inspect.aisi.org.uk/) — chosen for the
flexibility this needs: multi-step agent runs inside a Docker sandbox, a live
Camunda cluster per run, programmatic *and* LLM-judge scorers, and a trajectory
viewer for debugging. Lint stays the cheap always-on gate; evals are opt-in per
PR (a label) and report as a non-blocking signal.

## Two kinds of eval

| Kind | Asks | How it runs | Where |
|---|---|---|---|
| **Trigger** | Does the right skill load (and the wrong one stay out)? | one structured-output call — no agent, no tools, no sandbox | `evals/skills/<skill>/triggers.py` |
| **Outcome** | Does the agent reach the right result? | an agent in a Docker sandbox, often against a live cluster | `evals/skills/<skill>/outcomes.py` (single-skill) or `evals/scenarios/<id>/outcomes.py` (cross-skill) |

A **trigger** shows the model the skill catalog — the same `<available_skills>`
block the `skill` tool discloses (skill name + frontmatter `description`) — plus
a prompt, and asks which skills it would load. It reads no skill bodies and
touches no cluster, so it's ~3s and cheap. It measures *routing*: is the
`description` winning the prompts it should and staying out of the ones it
shouldn't.

An **outcome** eval runs a real agent loop end to end and checks what it
produced. Single-skill and cross-skill outcome evals use the exact same
machinery — the directory (`skills/` vs `scenarios/`) only signals scope.

## The agent loop (outcome evals)

Inspect's `react()` loop with three tools: `bash_session`, `text_editor`, and
`skill(all_skill_dirs())` — the last surfaces all 13 skills to the model.
Cross-skill routing falls out of *which* skills the model chooses to load (a
transcript signal), not from seeding files. The model is picked with Inspect's
`--model` flag (local default `anthropic/claude-sonnet-4-6`; CI uses a Bedrock
Claude via the `EVAL_MODEL` repo variable). There is no CLI-harness bridge yet —
`react()` is the loop.

## Two-phase sandbox

Every outcome eval runs in two Docker phases: **Phase 1 is what the agent does;
Phase 2 is what we check.** They're separate containers so untrusted,
agent-written code (e.g. a CPT test in Java we then compile) runs isolated —
network egress denied, memory/CPU capped — apart from the cluster the agent used.

```
Phase 1 — Eval                          Phase 2 — Verify
┌────────────────────────────┐          ┌────────────────────────────┐
│ agent container + an        │          │ verifier container          │
│ orchestration service       │  /workspace  │ (egress denied, capped)  │
│ (camunda/camunda, H2)       │ ───ro──▶ │ re-deploys the agent's BPMN │
│                             │          │ and asserts behaviour       │
│ agent: prompt → bash /      │          │ (CPT, c8ctl, lint, judge…)  │
│ editor / skill → writes     │          │                             │
│ artifacts to /workspace     │          │ agent never sees this phase │
└────────────────────────────┘          └────────────────────────────┘
```

The agent container shares the orchestration service's network namespace, so
`localhost:8080` / `:9600` work from the agent's shell. The verifier mounts the
agent's `/workspace` read-only and walks it for `*.bpmn` / `*.form` / `*.dmn`,
so it picks up the artifacts whatever they're named.

## Scorers: gating vs diagnostic

An outcome eval declares its scorers in `outcomes.py`. Each is one of:

- **Gating** — decides pass/fail. Use the *cheapest* scorer that catches the
  failure mode you care about; deterministic before LLM-judge. Built today:
  the judge (`model_graded_qa`, rubric in `Sample.target`), `feel_evaluates_to`,
  `bpmn_lint_clean`, `process_deployed_on_cluster`, `cpt_scorer`.
- **Diagnostic** — shown, never fails the build: `assert_skill_loaded(...,
  gating=False)` records whether the agent actually read the skill.

Stack any combination — rocket-launch gates on deploy + lint + CPT, each catching
a different failure mode.

## `with_skill` / `without_skill`

An outcome eval can run two arms (the `arm` task parameter):

- **`with_skill`** (default) — every skill available. The real condition, and
  the *gated* arm.
- **`without_skill`** — the load-bearing skill(s) named in
  `without_skill_excludes` (default: the skills under test) are switched off;
  every other skill stays available.

The point is the **delta**: run the task with the skill, then with it switched
off — the difference on the gating scorers is what the skill actually buys you.
If both arms pass equally, the skill may not be earning its keep. `without_skill`
is a *comparison, not a bar* — it's never gated. Triggers can't do this (you
can't measure "the right skill loads" with it removed), so they run one arm only.

## The cost baseline (tokens only)

Each outcome eval dir holds an `outcomes_baseline.json` recording, per arm, each
passing sample's token count (plus turns and tool-calls):

```json
{
  "model": "anthropic/bedrock/global.anthropic.claude-sonnet-4-6",
  "with_skill": {
    "samples": {
      "gateway-condition": { "tokens": 4200, "turns": 3, "tool_calls": 2 }
    }
  }
}
```

A few terms, plainly:

- **Epoch** — one run of a sample. Running an eval at *3 epochs* runs each
  prompt three times, to tell a stable result from a flaky one.
- **Median** — the middle of those runs. The baseline stores the **median across
  epochs** so one weird outlier run doesn't set the number.
- **The `× 1.5` ceiling** — a sample may spend up to **1.5× its recorded
  tokens** before the gate flags it. Loose enough to absorb normal run-to-run
  wobble, tight enough to catch a real blow-up. It's a coarse cost *tripwire*,
  not a precise budget.

What's gated and what isn't:

- **Only `tokens` is gated.** `turns` and `tool_calls` are stored purely so the
  summary can show a *delta* ("+20% tokens, +2 turns") and point at *why* a cost
  moved — they're never a ceiling of their own (a second gate on noisy,
  correlated counts would just flake).
- **Outcome correctness is gated by the scorers, never the baseline.** The
  baseline is a cost ceiling, full stop.
- **Only passing samples get an entry.** A failed or errored run's numbers are
  unrepresentative (a token-limit flail inflates them, an early error deflates
  them), so they're skipped until the sample passes.
- **Adding a sample never breaks others** — a new id simply has no baseline yet
  and is reported, not gated.

Token counts are **model-specific**, so baselines are regenerated on CI against
the canonical model (see [`ci.md`](ci.md)), not from a laptop. Triggers have no
baseline.

## What this suite is *not*

- Not a replacement for `waza check` — they run alongside, on different questions.
- Not a description-optimization loop — skill descriptions are rewritten by hand.
- Not a place for speculative evals — each one should catch a failure mode
  someone has observed or has a clear hypothesis about. An eval without a concrete
  failure-mode is dead weight: it gets ignored when it fails, or regenerated when
  it's in the way.
