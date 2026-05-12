# Skill Evaluation Framework

This document is the reference for the eval/test setup that ships with
`camunda/skills`. It explains the concepts, the artifacts, the runtime flow,
and how to extend the framework when you add a new skill or a new verifier.

For day-to-day commands, see the root `Makefile` (`make help`). For the
internals of `tools/eval-runner` itself (data flow inside the harness, SDK
contract, SHA-pin update procedure), see
[`tools/eval-runner/AGENTS.md`](../tools/eval-runner/AGENTS.md). This file is
the tier above both: what the framework is and why the pieces exist.

If you're new to evals or want a friendlier walkthrough of the same concepts
(including a plain-English unpack of the asymmetric regression rule), open
[`evals-explained.html`](evals-explained.html) in a browser.

---

## Goals

A skill repo is a quality artefact. Each skill claims to make Claude better at
some Camunda task — but "better" is fuzzy. Without measurement, we can't tell
whether a description change actually improves discovery, whether new
reference material lifts task quality, or whether a refactor regressed
something. This framework turns those questions into runnable, reviewable
numbers so we can move skills forward safely.

Concretely it answers three questions per skill:

1. **Discovery**: when the user has a task this skill should handle, does
   Claude actually load the skill? (Tier 1 — trigger eval, F1 over positive
   and negative probes.)
2. **Quality**: when the skill IS loaded, does Claude do better than without
   it? (Tier 2 — paired `with_skill` / `without_skill` runs scored by an
   LLM judge against per-case `expectations[]`.)
3. **Correctness**: where the answer is deterministic — a FEEL expression
   that should evaluate to a specific value, a BPMN file that should pass
   `c8 bpmn lint` — does the answer actually hold up against the real
   tooling? (Tier 2 verifiers, post-grading.)

Plus a structural pre-flight (Tier 0 — `tools/skill-lint`) that validates
frontmatter, schemas, cross-references, and other deterministic
correctness checks fast and free.

---

## The three tiers at a glance

| Tier | What | Cost | Where it runs | When |
|---|---|---|---|---|
| 0 | Lint | Free, milliseconds | Pre-commit, PR CI | Every PR |
| 1 | Trigger probes (does the description grab the right cases without over-triggering?) | ~$0.05 / case-trial | PR CI on changed skills, nightly full | Every changed-skill PR + nightly |
| 2 | Quality + verifiers (does the skill actually help vs. not having it?) | ~$0.20 / arm-trial | Same as Tier 1 | Same as Tier 1 |
| 3 | Cross-agent / behavioral | Deferred — see "Future" | n/a | n/a |

Tier 0 must always pass. Tier 1/2 are gated by regression thresholds vs the
committed `baseline.json` — see "How to interpret your numbers" below.

---

## Skill flavors and what "good" looks like

Not all skills should look the same on the dashboard. Two flavors land
naturally on this repo, and they have different expected baselines:

**Knowledge-additive skills** teach the agent something it doesn't already
know. Examples likely to live here: `camunda-bpmn` (Zeebe extensions are
proprietary), `camunda-forms` (Camunda Form JSON shape is proprietary),
`camunda-connectors` (element-template wiring), the `camunda-c8ctl`/
`-deploy`/`-operate` skills (entirely-proprietary CLI surfaces).

  - **Trigger discovery should be high.** F1 ≥ 0.7 is reasonable; the
    skill describes territory the agent doesn't have a strong default
    answer for, so the description's pull beats "answer directly".
  - **`skill_help` (with − without) should be large.** Often 30–70pp.
    Without the skill, the agent invents wrong syntax / commands /
    schema keys.
  - **Tier 2 verifiers will catch most regressions cleanly** (the BPMN
    lints, the form renders, the CLI exits 0).

**Correctness-protective skills** are about a topic the agent mostly
knows from training but has subtle gotchas. Example: `camunda-feel`. FEEL
is well-trained-on, so:

  - **Trigger discovery is naturally lower.** F1 of 0.20–0.40 is normal
    — the agent often answers without invoking the skill because the
    topic is familiar. That's fine if quality holds up; not fine if it
    doesn't.
  - **`skill_help` is small but non-zero.** Often 5–25pp. The skill
    catches the rare gotcha (FEEL's strict typing, multi-entry context
    syntax) but not every prompt exercises one.
  - **Per-case data matters more than aggregates.** A correctness-
    protective skill's value lives in the few cases where the agent
    would otherwise trip; aggregate pass-rate masks them.

When you're authoring a new skill, write down which flavor you expect it
to be in the case-set's `evals/README.md`. Reviewers should expect very
different shapes from a `c8ctl` baseline vs a `feel` baseline; the
asymmetric regression rules below were designed to handle both without
needing per-skill threshold knobs.

---

## How to interpret your numbers

The `compare` step writes a markdown delta block into the PR comment with
two tables: **Quality (the headline)** and **Discovery (secondary)**.
That order is deliberate — the question we actually care about is "does
having this skill loaded make the agent better?", measured by `skill_help =
with_skill_pass_rate − without_skill_pass_rate`. Trigger metrics live
under "Discovery" because they tell us whether the skill description is
finding its audience, not whether the skill is doing its job.

### What each metric tells you

**Quality block:**

| Metric | What it answers | Drop response |
|---|---|---|
| `skill_help` | The skill is making the agent better by this much | **Regression at >5pp drop.** This is the headline reason the skill exists. |
| `with_skill_pass_rate` | When the skill IS loaded, how often does the agent succeed? | **Regression at >5pp drop.** A drop here means the skill content got worse. |
| `without_skill_pass_rate` | If we removed the skill, how would the agent do? | Informational. Rises mean training caught up; falls mean the agent now needs the skill more. Neither is automatically a regression, but both shift `skill_help`. |

**Discovery block:**

| Metric | What it answers | Drop response |
|---|---|---|
| `precision` | Of the times the skill triggered, how often was the trigger right? | **Regression at >5pp drop.** Precision falling means over-triggering grew — the skill is grabbing prompts it shouldn't, wasting context. |
| `recall` | Of the prompts that should trigger the skill, how often did it? | **Warn-only.** Low recall is acceptable when `without_skill_pass_rate` is high (the agent answers fine unaided). It only matters in concert with low quality. |
| `F1` | Harmonic mean of precision and recall | **Informational.** Derived from precision and recall; we don't regress on it independently. |

### The asymmetric regression rule

This is the rule the runner enforces. Each metric has its own threshold
and severity:

| Metric | Drop threshold | Severity | Rationale |
|---|---|---|---|
| `with_skill_pass_rate` | 5pp | **regression** | Skill made things worse |
| `skill_help` | 5pp | **regression** | Skill helps less than before |
| trigger `precision` | 5pp | **regression** | Over-triggering grew |
| trigger `recall` | any | **warn** | Under-triggering is fine if quality holds |
| trigger `F1` | any | **informational** | Components carry the rule |

A regression fails the PR check; a warning posts the markdown delta but
exits 0. The harness uses these rules uniformly across skill flavors —
flavor is a labeling/expectation tool for reviewers, not a per-skill
threshold knob.

### Reading a regression report in practice

A few patterns to recognize:

  - **`skill_help` flat, `with_skill_pass_rate` flat, `recall` dropped**:
    safe to merge. The agent is choosing not to load the skill on
    prompts the description claims, but quality didn't suffer because
    those prompts didn't actually need the skill. The description may
    be over-claiming; iterate on `triggers.json` next time but don't
    block this PR.
  - **`with_skill_pass_rate` flat, `without_skill_pass_rate` rose,
    `skill_help` dropped**: also safe to merge — the model improved
    independently. Eventually you may decide to retire the skill or
    repurpose it (the natural exit ramp for correctness-protective
    skills).
  - **`precision` dropped, others stable**: regression. Description
    grew too aggressive. Tighten the trigger phrases or the negative
    cases that newly trigger.
  - **`with_skill_pass_rate` dropped**: regression. Inspect per-case
    data — usually one or two cases fell off. Look at the trial
    `transcript.jsonl` and the failing `grading.json` evidence text.

---

## Concepts and artefacts

### Skill

A directory under `skills/` with a `SKILL.md` (frontmatter + body), optional
`references/`, optional `scripts/`, and an `evals/` subdirectory containing
the eval inputs.

```
skills/camunda-feel/
├── SKILL.md
├── references/
│   ├── common-patterns.md
│   └── function-reference.md
└── evals/
    ├── evals.json            # quality cases + verifiers (Tier 2)
    ├── triggers.json         # positive/negative trigger probes (Tier 1)
    └── baseline.json         # committed comparison point
```

### `evals.json` — quality cases (Tier 2 input)

```jsonc
{
  "skill_name": "camunda-feel",
  "evals": [
    {
      "id": "basic-expression",
      "prompt": "Write a FEEL expression... Write your final FEEL expression to outputs/answer.feel.",
      "expected_output": "<prose hint for the judge>",
      "expectations": [
        "Use if-then-else with an else branch",
        "Apply 0.15 or 15/100 as the discount rate",
        "..."
      ],
      "verifiers": [
        {"type": "feel-evaluate", "context": {"orderAmount": 1500}, "expected": 1275}
      ]
    }
  ]
}
```

Per case:
- `id` — kebab-case slug, stable across reorderings.
- `prompt` — what we send to the agent. Should explicitly tell the agent
  where to write its final output (e.g. `outputs/answer.feel`).
- `expectations[]` — prose checks the LLM judge grades against.
- `verifiers[]` — optional deterministic post-checks. Each entry is
  dispatched to a verifier module (see "Verifiers" below). Cases without a
  deterministic answer (e.g. `today()`-dependent) keep `verifiers: []`.

A trial **passes** when the judge's pass rate over `expectations[]` is at
least `QUALITY_PASS_THRESHOLD` (currently 0.5) AND every non-skipped
verifier passes. A skipped verifier (e.g. cluster unreachable, `c8` not on
PATH) does not block the trial — it's recorded in `summary.json` so the
reviewer can see what wasn't checked.

### `triggers.json` — discovery probes (Tier 1 input)

```jsonc
{
  "schema_version": 1,
  "skill": "camunda-feel",
  "discoverability": {"mode": "all_skills"},
  "positive": [
    {
      "id": "pos-gateway-condition",
      "prompt": "Write a condition that routes to premium when total > 1000...",
      "expected_load": ["camunda-feel"],
      "expected_dependencies": [],
      "must_not_load": []
    }
  ],
  "negative": [
    {
      "id": "neg-juel-conversion",
      "prompt": "Convert this JUEL expression to Camunda 7 syntax: ${...}",
      "expected_load": [],
      "must_not_load": ["camunda-feel"]
    }
  ]
}
```

Positive cases are situations where the skill *should* trigger. Negatives
are near-miss situations where it should *not* (over-triggering wastes
context and confuses the agent). Aim for ~10 of each, varying phrasing,
explicitness, and the surface symptoms of the underlying task.

### `baseline.json` — the committed comparison point

A snapshot of a known-good iteration's headline metrics, pinned in the
repo at `skills/<name>/evals/baseline.json` so PRs can be compared against
it deterministically. Schema lives at
`tools/skill-lint/schemas/baseline.schema.json`.

```jsonc
{
  "schema_version": 1,
  "skill": "camunda-feel",
  "established_at": "2026-05-04T...",
  "established_by": "<git short SHA>",
  "source_iteration": "evals/camunda-feel/iteration-7",
  "model": {
    "provider": "anthropic",
    "id": "claude-opus-4-7",
    "harness": "claude-agent-sdk",
    "judge": "claude-sonnet-4-6"
  },
  "trials_per_case": 3,
  "triggers": {"f1": 0.91, "precision": 0.93, "recall": 0.89, ...},
  "quality": {
    "with_skill": {"pass_rate": 0.88, "n_cases": 4, "n_trials": 12},
    "without_skill": {"pass_rate": 0.42, "n_cases": 4, "n_trials": 12},
    "delta_pp": 46.0,
    "per_case": [...]
  },
  "regression_thresholds": {
    "with_skill_pass_rate_drop_pp": 5.0,
    "trigger_f1_drop_pp": 5.0,
    "sustained_runs": 2,
    "noise_floor_pp": 8.3
  }
}
```

Promotion is deliberate, never automatic. `make promote SKILL=<name>`
copies a chosen iteration's results into `baseline.json` after the
worktree is clean (refuses to run on dirty trees unless `--force`). Treat
a baseline bump like a code change: it lands in its own PR with a clear
"why this is the new bar" rationale.

### `evals/<skill>/iteration-N/` — per-run workspace

Generated. Gitignored at the top-level `/evals/`. One directory per
`make eval` invocation:

```
evals/camunda-feel/iteration-3/
├── summary.json          # machine-readable headline metrics
├── report.html           # self-contained reviewer report
├── triggers/
│   ├── summary.json
│   └── run_eval_raw.json # raw stdout from anthropics/skills' run_eval.py
├── with_skill/
│   └── <case-id>/
│       └── trial-N/
│           ├── eval_metadata.json
│           ├── outputs/answer.feel        # what the agent wrote
│           ├── transcript.jsonl           # SDK message stream
│           ├── tool_uses.json             # captured ToolUseBlocks + skill loads
│           ├── timing.json
│           ├── grading.json               # LLM judge verdict
│           └── verifier_results.json      # post-grading checks
└── without_skill/
    └── ...                                 # mirror of with_skill/
```

`evals/<skill>/index.html` is regenerated alongside listing all iterations
with their headline metrics and links to each `report.html`.

---

## The runtime flow

Three entry points: `make lint`, `make eval-triggers`, `make eval-quality`.
The big-button `make eval` runs both eval tiers into one iteration.

```
make eval SKILL=camunda-feel
│
├── make eval-triggers
│     └── tools/eval-runner/trigger_eval.py
│           subprocess: python -m scripts.run_eval         (their code)
│             └── shells to claude -p with --include-partial-messages
│                 to detect skill triggering early from stream events
│           ← parses stdout JSON, projects to summary.json with F1 added
│
└── make eval-quality
      └── tools/eval-runner/quality_eval.py
            for each (case × arm × trial):
              ├── tools/eval-runner/sdk_runner.py
              │   isolated_workdir + claude_agent_sdk.query()
              │     - ClaudeAgentOptions.skills filters target out for
              │       without_skill arm
              │     - captures ToolUseBlocks for skill-load detection
              │       (Skill tool primary, Read of SKILL.md fallback)
              │     - cwd=/tmp/eval-trial-* sandboxes stray writes
              │     - copies <tmp>/outputs/* back into trial dir
              │
              └── tools/eval-runner/sdk_runner.run_grader()
                  - system prompt = SHA-pinned agents/grader.md
                  - tools restricted to Read + Write
                  - writes grading.json per its own instructions
              │
              + tools/eval-runner/verifiers/run_all()
                - dispatches case.verifiers[i] by .type to the
                  matching module (e.g. feel_evaluate.py)
            ↓
            aggregate(trial_outcomes) → summary.json
            ↓
            report.render_iteration() → report.html
            report.render_index() → ../index.html
```

### What the SDK does for us

The harness uses `claude-agent-sdk` (PyPI), a typed Python wrapper over
the same headless `claude -p` CLI. It gives us:

- Async iteration over a typed message stream.
- `ToolUseBlock` dataclasses with `name` and `input`, so skill-load
  detection is structural — `block.name == "Skill"` with `input.skill =
  "<name>"` (primary) or `block.name == "Read"` with `SKILL.md` in
  `input.file_path` (fallback). Not a free-text scrape.
- `ClaudeAgentOptions.skills=[...]` to control which skills are visible
  per-arm. The **without_skill arm** filters the target out; siblings
  remain available, matching plugin-install reality.
- `ResultMessage.total_cost_usd`, `duration_ms`, `usage` for cost and
  timing accounting.
- `max_budget_usd` per query as a hard cap.

### Why isolation matters

`permission_mode="bypassPermissions"` is required for non-interactive
runs (no TTY for prompts), but it bypasses ALL path checks. An over-eager
agent can do `Write /home/user/skills/outputs/answer.feel` and reach
committed source. The harness counters this with a per-trial
`isolated_workdir()` under `/tmp/eval-trial-*`: skills are symlinked in
under `<tmp>/.claude/skills/`, so discovery still works, but stray
absolute-path writes land in /tmp and are reclaimed when the temp dir is
cleaned up. After the run, `<tmp>/outputs/*` is copied back into the
trial's persistent `outputs/` dir.

### Skill-creator reuse

`tools/eval-runner/.skill-creator-sha` pins a SHA from
`anthropics/skills`. `make setup-skill-creator` shallow-clones to
`tools/external/anthropics-skills/` (gitignored). The harness reads two
files from there:

- `skills/skill-creator/scripts/run_eval.py` — driver for the trigger
  eval (subprocess, computes F1).
- `skills/skill-creator/agents/grader.md` — system prompt for the grader
  call.

Vendoring copies into our repo would drift; submodules add a
clone-time UX gotcha. SHA pin is one diff per upgrade.

The full update procedure is in
[`tools/eval-runner/AGENTS.md`](../tools/eval-runner/AGENTS.md).

---

## Verifiers

A verifier is a deterministic post-grading check that runs against the
agent's emitted output files. It cannot fix a wrong prose answer, but it
can catch an answer that *reads* right and is *behaviorally* wrong.

```python
# tools/eval-runner/verifiers/<type>.py

VERIFIER_TYPE = "feel-evaluate"      # matched against verifiers[].type

def run(verifier: dict, case: dict, outputs_dir: Path, repo_root: Path) -> Result:
    ...
    return Result(type=VERIFIER_TYPE, passed=..., message=..., details={...})
```

Modules in `tools/eval-runner/verifiers/` that expose `VERIFIER_TYPE` and
a `run` callable are auto-discovered. The orchestrator iterates each
case's `verifiers[]` and dispatches each entry to the matching module.

`Result.skipped=True` with a `skip_reason` is the documented
"could not run the check" state — it does NOT block the trial. Pass
criteria, in order of precedence:

1. Any non-skipped verifier failure → trial fails.
2. Else, judge `pass_rate >= QUALITY_PASS_THRESHOLD` → trial passes.

### Existing verifier: `feel-evaluate`

Reads `outputs/answer.feel` and shells to `c8 feel evaluate '<expr>'
--vars '<json>'`. Compares the trimmed stdout to `expected`, with type
coercion (int/float/string/bool/null/list/dict).

Engine policy: cluster by default, never silent fallback. Setting
`EVAL_FEEL_ENGINE=local` is an explicit opt-in for offline integration
tests where no cluster is reachable. For pure FEEL semantics on
supported expressions, the local engine is interchangeable with the
cluster engine (same result, same parse-error exit codes, same
warn-then-null on unknown variables); real differences are
cluster-only features (`--tenant`, transport failures) and warning
payload shape. Baselines should still run against cluster to catch
infrastructure-level regressions.

### Existing verifier: `bpmn-lint`

Reads `outputs/process.bpmn` (or whatever `verifier.answer_file`
overrides to) and shells to `c8 bpmn lint <file> --quiet`. Both
quiet and non-quiet modes exit non-zero on parse failures or lint
violations; `--quiet` is used to suppress the `✓ No issues found.`
success line so the verifier output is clean when there's nothing
to report.

There's no `expected` field — passing means the BPMN parses and
lints clean against the c8ctl-bundled `bpmnlint` ruleset. Failure
captures the trailing `✖ N problems (...)` summary line in the
result message and the full report in `details.report` for the
viewer. There's no cluster dependency (lint runs entirely
client-side), so no `no-cluster` skip path — only `no-cli` (when
`c8` is missing from PATH) or `no-output-file` (when the agent
didn't emit).

### Verifier roadmap (deferred)

Each rollout in Phase 4 adds the verifier its skill needs:

| Skill | Verifier | Status |
|---|---|---|
| camunda-feel | `feel-evaluate` | done |
| camunda-bpmn | `bpmn-lint` (`c8 bpmn lint --quiet`) | done |
| camunda-forms | `form-render` (forms-js) | future |
| camunda-connectors | `connector-applied` (`c8 element-template apply` + lint) | future |
| camunda-deploy | `cli-exit` + `cluster-intercept` | future |
| camunda-operate | `transcript-shape` (CLI call sequence) | future |
| camunda-c8ctl | `profile-state` (post-condition inspection) | future |

CPT-based BPMN behavioral verification (Camunda Process Test) is also
deferred — see "Future" below.

---

## Cross-skill design

The repo has multiple skills. The framework has opinions about how they
relate at eval time.

- **No frontmatter `dependencies` field** and no runtime auto-load. Body-
  prose `## Cross-References` (existing convention) stays. Progressive
  disclosure decides at runtime, like in production.
- **The runner exposes ALL repo skills to the agent under test**, except
  the target in the without_skill arm. This matches plugin-install
  reality and avoids over-isolating the agent into a single-skill
  fantasy world.
- **`expected_dependencies` is a per-case assertion**, not an
  instruction. Today: recorded but not yet enforced. When we add a
  skill that genuinely depends on another (e.g. a hypothetical
  `camunda-app` that should pull in `camunda-bpmn` and `camunda-forms`
  for a particular case), the recorded `loaded_skills` lets us check
  whether the cross-skill load actually happened.

---

## Lifecycle: bootstrap → iterate → promote → regress

A skill goes through four states. The framework's commands map onto each
transition.

1. **Bootstrap.** No `baseline.json` yet. Run `make eval SKILL=<name>`,
   inspect `report.html`, iterate on `evals.json` cases until they
   exercise meaningful skill differentiators (without_skill should fail
   meaningfully, not just slightly). When you're happy with the
   iteration, `make promote SKILL=<name>` writes the first
   `baseline.json`. **`make compare` returns `status: bootstrap`, exit 0
   in this state**, so PRs against an unbaselined skill never block on
   regression.

2. **Iterate.** Each PR that touches `skills/<name>/` triggers a fresh
   iteration in CI. `make compare SKILL=<name>` posts a markdown delta
   on the PR. Drops up to 2pp are silent (within noise floor); 2-5pp
   warn; >5pp on either trigger F1 or `with_skill.pass_rate` fails the
   PR check. Improvements show with ▲ arrows in the report.

3. **Promote.** When you've genuinely improved the skill, run
   `make eval SKILL=<name> RUNS=3` locally (or trigger it from CI),
   inspect, then `make promote SKILL=<name>`. The bump lands in its
   own PR.

4. **Regress.** If a refactor regresses a skill below the floor and we
   ship anyway (rare but real — e.g. removing a deprecated example),
   the same `make promote` pattern moves the floor downward. Treat that
   as a deliberate decision, not an automatic one.

---

## Adding evals to a new (or existing) skill

Recipe, end-to-end:

1. **Lint your `SKILL.md` first.** `make lint SKILL=<name>` should be
   clean before you touch evals.

2. **Write `triggers.json`** with ~10 positive + ~10 negative cases.
   Vary phrasing on positives. Negatives should be near-misses to catch
   over-triggering. See `skills/camunda-feel/evals/triggers.json` for
   the canonical shape.

3. **Extend `evals.json`** with cases that genuinely need the skill.
   The without_skill arm is your control: if Claude can answer the
   prompt without the skill loaded (because the topic is well-trained-
   on), the case won't show a delta no matter how good your skill is.
   Bias toward cases that exercise:
   - Skill-specific syntax / functions (e.g. `bpmnError()`, `fromAi()`)
   - Footguns the skill warns about (e.g. type-coercion silent nulls)
   - Camunda-version-specific behavior
   - Error-message debugging (the agent has the trace; the skill has
     the explanation)
   - Cross-references to other skills' artefacts (a BPMN file + a FEEL
     condition referenced from it)

4. **Add `verifiers[]` where the answer is deterministic.** Cases like
   "what's today's due date" have no deterministic ground truth; leave
   `verifiers: []` and rely on the prose judge. Cases with a fixed
   answer for fixed input (the typical case) get one or more
   `feel-evaluate`-style entries with `context` + `expected`.

5. **Make sure prompts tell the agent where to write its output.** The
   verifier reads from `outputs/answer.feel` (or whatever
   `verifier.answer_file` says). Phrase the prompt: "Write your final
   FEEL expression — and only the expression, no fences, no commentary
   — to `outputs/answer.feel`." Without that direction, the agent might
   embed the answer in prose only and the verifier skips with
   `no-output-file`.

6. **Rehearse cheaply.** `make eval SKILL=<name> RUNS=1` runs all cases
   one trial each. Look at `report.html`:
   - Trigger F1 should be at least 0.5 — if not, the description is
     not pulling.
   - At least one case should show `with_skill > without_skill` —
     otherwise the skill isn't differentiating.
   - All verifiers should run (`engine: cluster` in details). If
     they're all `skipped: no-cli` your `c8` install is missing; if
     `no-cluster`, set `EVAL_FEEL_ENGINE=local` for integration
     testing only.

7. **Promote.** Once the rehearsal looks good, run with `RUNS=3` for
   the real baseline, then `make promote`.

---

## Cost discipline

Per-trial-call costs observed on `camunda-feel` rehearsals:

| Stage | Per call | Notes |
|---|---|---|
| Trigger probe | ~$0.05 | One `claude -p` per (case × trial), gated by `--include-partial-messages` |
| Quality with_skill | ~$0.20 | One full SDK run per (case × trial) |
| Quality without_skill | ~$0.14 | Slightly cheaper (no skill body in context) |
| Grader | ~$0.05 | Sonnet, restricted-tool agent over the trial transcript |

Full 3-trial baseline for camunda-feel (~20 trigger cases + 4 quality
cases × 2 arms): **~$8.50**.

Knobs:

- **`RUNS=N`** — drop to 1 for cheap rehearsals; CI on PRs uses 1; nightly
  uses 3.
- **`--max-usd <X>`** on the runner — soft top-level budget guard.
- **`--arm-max-usd`, `--grader-max-usd`** — per-call caps surfaced from
  `ClaudeAgentOptions.max_budget_usd`. Default $1.0 / $0.5.
- **`--concurrency N`** — bounded async semaphore across all (case × arm
  × trial) coros. Default 4.
- **`--skip-triggers`, `--skip-quality`** on `run` to slice the work.

If a skill's eval matrix grows past 50 trials per run, revisit case
count or pin `RUNS=2` in CI. The harness scales linearly; cost is
dominated by total-trial-count × average call cost.

---

## Operational gotchas worth knowing

- **`run_eval.py` invocation.** Run with `python -m scripts.run_eval`
  and `PYTHONPATH=<…>/skill-creator`. Calling the script directly
  fails with `ModuleNotFoundError: scripts` because the upstream uses
  `from scripts.utils import ...` style.
- **Root user blocks `--dangerously-skip-permissions`.** Claude Code
  refuses bypass under root unless `IS_SANDBOX=1` is in the env. The
  SDK harness sets it for both arm and grader runs.
- **`bypassPermissions` ignores `add_dirs`.** The agent can write
  absolute paths anywhere. Always run the agent inside `/tmp` via
  `isolated_workdir()`; never give the agent a cwd inside the repo
  tree.
- **`run_eval.py` injects a slash-command stub** at
  `<project_root>/.claude/commands/<skill>-skill-<uuid>.md` and
  cleans it up in a `finally`. We run it from the repo root so its
  `find_project_root()` walks to ours, not the upstream clone's.
- **Dry runs produce reports too.** `make eval-dry SKILL=<name>` writes
  scaffolding plus a `report.html` so you can sanity-check the layout
  before spending money.
- **Reports embed paths relative to the iteration dir.** `paths.py`
  rewrites any string starting with `<workspace_root>` so committed
  baselines never leak machine identity (`/home/user/...`,
  `C:\Users\...`). The grading_paths lint rule defends in depth.

---

## Future / explicitly deferred

The plan keeps a list of items that are out of scope for v1 but worth
revisiting:

- **CPT-based BPMN behavioral verification.** Spinning up Zeebe
  Testcontainers per case to run the BPMN under test, then asserting
  on element-instance state. Significant infra; revisit after Phase 4
  rollouts land.
- **Cross-agent matrix.** Today the harness drives only Claude Code via
  `claude-agent-sdk`. A future cross-agent eval would run Codex CLI,
  Gemini CLI, Copilot CLI through Harbor adapters or `upskill`.
- **Sustained-runs regression rule.** Plan called for "regress only
  after 2 consecutive runs over threshold". Single-run is sufficient for
  v1; the implementation needs git-history plumbing that hasn't paid
  for itself yet.
- **Auto-optimization of skill descriptions.** `skill-creator`'s
  `run_loop.py` exists upstream but isn't wired in here. Use ad-hoc
  during authoring; not part of CI.
- **Composite skills.** No skill in the repo currently fans out to
  others (e.g. a `camunda-app` skill that pulls `camunda-bpmn` +
  `camunda-forms`). The cross-skill design supports this via
  `expected_dependencies`; we wire it when the first composite lands.

---

## Where to look next

- [`tools/eval-runner/AGENTS.md`](../tools/eval-runner/AGENTS.md) —
  harness internals, SDK contract, SHA-pin update procedure.
- [`tools/skill-lint/`](../tools/skill-lint/) — Tier-0 rules and
  schemas.
- [`tools/eval-runner/verifiers/`](../tools/eval-runner/verifiers/) —
  existing verifiers and the dispatch contract.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — adding a new skill,
  high-level checklist.
- `skills/camunda-feel/evals/` — canonical example of the artefact
  shapes documented above.
