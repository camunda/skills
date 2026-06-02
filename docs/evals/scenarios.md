# Eval suite — authoring & running

How to add and run evals. For the "why" (sandbox model, baseline semantics),
see [`concepts.md`](concepts.md).

## Two kinds of eval

| Kind | Question | Authored as | Where |
|---|---|---|---|
| **Trigger** | Does the right skill load (and the wrong one stay out)? | Python `triggers.py` | `evals/skills/<skill>/triggers.py` |
| **Result** | Does the agent reach the right result? | Python `task.py` | `evals/skills/<skill>/task.py` (per-skill) or `evals/scenarios/<id>/task.py` (cross-skill) |

A trigger is a single structured-output routing call (no agent, no sandbox);
its samples are inlined in the skill dir's `triggers.py`. Result evals are
bespoke — they pick scorers (LLM judge and/or programmatic) and may use a live
cluster — so each is a small Inspect `task.py` and runs in a Docker sandbox.

## Adding a trigger eval (Python)

Create or edit `evals/skills/<skill>/triggers.py` — a thin `@task` that inlines
its samples and calls `build_trigger_eval`:

```python
"""Trigger eval for camunda-feel — does this prompt route here?"""
from pathlib import Path
from inspect_ai import Task, task
from core.triggers import Negative, Positive, build_trigger_eval

@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,        # the skill = this directory
        positive=[                          # prompts that SHOULD load it
            Positive("gateway-condition",
                     "What FEEL expression takes a flow only when amount > 1000?"),
        ],
        negative=[                          # prompts that should route elsewhere
            Negative("author-process", "Design a BPMN process for invoice approval.",
                     should_load=["camunda-bpmn"]),   # optional: where it routes instead
        ],
    )
```

The target skill is implicit: every `Positive` asserts `should_load=[<skill>]`
and every `Negative` asserts `should_not_load=[<skill>]` — so you never repeat
it. Sample ids are auto-prefixed `pos-` / `neg-`. Optional extra guards:
`Positive(..., should_not_load=[...])` keeps a sibling out on a positive prompt;
`Negative(..., should_load=[...])` names where it should route instead. Two more
optional `build_trigger_eval` kwargs: `excluded_skills=[...]` hides skills from
the routing catalog, and `also_run_when_changed=[...]` widens the CI
changed-skills filter (no runtime effect).

Run it: `make eval-trigger SKILL=camunda-feel`.

## Adding a result eval (Python)

A result eval is an Inspect `task.py` with a module-level `METADATA` and an
`@task`. Per-skill evals live in `skills/<skill>/`, cross-skill ones in
`scenarios/<id>/`. Copy the closest existing one:

- judge-scored, text-only → `skills/camunda-development/task.py`
- deterministic + cluster → `skills/camunda-feel/task.py`
- deploy + lint + CPT → `scenarios/rocket-launch/task.py`

```python
METADATA = ScenarioMetadata(
    skills=["camunda-feel"],                       # CI changed-skills filter
    baseline=BaselineConfig(exclude=["camunda-feel"]),  # what without_skill drops
)

@task
def camunda_feel(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.baseline.exclude)
    return Task(
        dataset=[...],
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[feel_evaluates_to(), assert_skill_loaded("camunda-feel", gating=False)],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
    )
```

Scorer options (compose any in the `scorer=[...]` list):

- **Judge** — Inspect's `model_graded_qa(instructions=...)` against a per-sample
  rubric in `Sample.target`.
- **Deterministic** — `feel_evaluates_to()` (runs the agent's FEEL on the
  cluster), `bpmn_lint_clean()`, `process_deployed_on_cluster(id)`, `cpt_scorer(...)`.
- **Diagnostic skill-load** — `assert_skill_loaded(target, gating=False)`:
  shown, not gated. The with/without-skill delta is the routing signal.

Pick the sandbox by what the scorers need: `compose-advisory.yaml` (no cluster),
`compose-with-c8ctl.yaml` (live cluster), `compose-cpt-verifier.yaml` (cluster +
CPT). Anything more bespoke (e.g. WireMock) → drop a `compose.yaml` next to the
`task.py` and reference it.

Run it: `make eval-result SKILL=camunda-feel` (or `make eval SCENARIO=<id>` for a
scenario). No workflow edit — CI picks it up from `metadata.skills`.

## Running

```bash
make eval-images                       # build the sandbox images once
make eval-trigger  SKILL=camunda-feel  # one trigger eval
make eval-triggers                     # every trigger eval
make eval-result   SKILL=camunda-feel  # one per-skill result eval
make eval          SCENARIO=rocket-launch          # one scenario
make eval-result   SKILL=camunda-feel ARM=without_skill   # the comparison arm
make eval-viewer                       # open the Inspect trajectory viewer
```

`make help` lists every target. Default model is `anthropic/claude-sonnet-4-6`
(needs `ANTHROPIC_API_KEY`); override with `MODEL=…`.

## Baselines

`baseline.json` (per eval directory) records each sample's observed token count
per arm; the gate fails a sample whose tokens exceed `baseline × 1.5`. Outcome
is gated by the scorers, not the baseline. Triggers have no baseline (outcome
only).

```bash
make eval-result SKILL=camunda-feel        # fresh run
make eval-baseline TARGET=camunda-feel     # rewrite baseline.json from it
git diff evals/skills/camunda-feel/baseline.json   # review before committing
```

Regenerate after an intentional change or a new sample. Do **not** regenerate to
paper over a regression or a flaky run — diagnose first. Adding a sample never
breaks others: a new id simply has no baseline entry until you regenerate.

## Debugging a failure

1. **Read the transcript:** `make eval-viewer` (or `uv run inspect view
   <downloaded-log-dir>` for a CI artifact).
2. **Reproduce a CPT failure outside the sandbox:** `cd
   evals/scenarios/<id>/cpt-verifier && mvn test`.
3. **Check for flake:** `... --epochs 3` (append via `ARGS="--epochs 3"`).
4. **Compare arms:** both arms failing → not a skill problem; both passing →
   the skill may not be earning its keep.

## CI

Maintainer-gated by PR label (see [`ci-and-results.md`](ci-and-results.md)):

- `evals:run` — targets whose skills intersect the changed skills
- `evals:run-all` — every target
- `evals:compare` — also run the without-skill arm of result/scenario evals

The gate (`evals-pass-fail`) reds the check on a missed outcome threshold or a
token-budget regression; it does not block merge. The PR comment carries the
per-eval outcome, token budget, and any with/without delta.
