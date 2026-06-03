# Eval suite — runbook

Run, read, add, and maintain evals — for contributors and AI agents alike. For
the mental model (two kinds, sandbox, arms, baseline) see
[`concepts.md`](concepts.md); for CI see [`ci.md`](ci.md).

## When to touch evals

| You're changing… | Do |
|---|---|
| A `skills/<X>/SKILL.md` or its `references/` | If a trigger targets `X` or an outcome eval lists `X` in `metadata.skills`, run it locally and check the result before pushing. |
| A skill's frontmatter `description` | Re-run that skill's **trigger** — the description is the only lever routing moves on. |
| A new skill | Ask: which failure mode would an eval catch? If you have one, propose it. If not, **leave evals untouched** — don't fabricate one. |
| Lint-only edits (whitespace, links, frontmatter) | Nothing — `waza check` covers it. |
| The harness itself (`evals/`, Makefile, workflows) | Run an affected target locally as a smoke test; update baselines only if you meant to. |

## Commands

| Command | Does |
|---|---|
| `make eval-images` | Build the Docker sandbox images (one-time; outcome evals only) |
| `make eval-triggers` | Run **all** trigger evals |
| `make eval-triggers SKILL=camunda-feel` | Run **one** skill's trigger |
| `make eval-outcomes TARGET=skills/camunda-feel` | Run **one** outcome eval (a `skills/` or `scenarios/` dir) |
| `make eval-outcomes TARGET=scenarios/rocket-launch ARM=without_skill` | …the comparison arm |
| `make eval-outcomes` | The **whole** outcome suite (slow + costly) |
| `make eval-viewer` | Open the trajectory viewer over `evals/logs` (`localhost:7575`) |
| `uv run evals-pass-fail` | Gate verdict for the latest log (pass a path for a specific one) |
| `uv run evals-summarize --log-dir logs/` | Render the run report (verdict, token split, per-eval tables); add `--detail` for the per-eval token column |
| `make eval-baseline TARGET=skills/camunda-feel` | Rewrite that eval's `outcomes_baseline.json` from its last run |
| `uv run evals-list` | List every target + the skills it covers |

**Prerequisites:** Docker with Buildx (outcome evals only — `make eval-images`
builds via `docker buildx bake`; Buildx ships with Docker Desktop and modern
docker-ce) and [uv](https://docs.astral.sh/uv/) — the harness auto-installs
Python deps via `uv sync`. Triggers need neither Docker nor a cluster.

**Credentials:** the default model is `anthropic/claude-sonnet-4-6` — `export
ANTHROPIC_API_KEY`. For another provider pass `MODEL=…` plus that provider's
creds (e.g. CI's Bedrock model `MODEL=anthropic/bedrock/global.anthropic.claude-sonnet-4-6`
with AWS creds in the environment). Read creds from the environment; never write
them to disk.

## The local loop

1. Edit a skill (`SKILL.md` body, or its frontmatter `description` for routing).
2. **Routing changed?** `make eval-triggers SKILL=<name>`.
3. **Behaviour changed?** `make eval-outcomes TARGET=skills/<name>` (add
   `ARM=without_skill` to see the delta).
4. Red? `make eval-viewer` → drill the failing sample.
5. Behaviour *intentionally* changed and tokens moved? Regenerate the baseline
   (below) and review the diff.
6. On the PR, a maintainer adds `evals:run` to run the affected targets in CI.
   See [`ci.md`](ci.md).

## Reading a trigger result

Two gating scorers, both must hit **1.0**:

- **`skill_loaded`** — of the *must-load* samples, were they all routed to?
  `< 1.0` ⇒ the skill's `description` isn't winning prompts it should.
- **`skill_not_loaded`** — of the *must-stay-out* samples, did the forbidden
  skills stay out? `< 1.0` ⇒ the skill (or a sibling) over-triggers, or the
  guard is too strict.

`mean` is over the samples that carry that assertion, so `skill_not_loaded =
0.500` with 2 negatives means exactly one failed. At these sample counts ignore
`stderr` — read the per-sample explanation instead (`uv run evals-pass-fail`, or
`make eval-viewer` for the sample that scored 0).

**The lever is the skill `description`.** Edit it, re-run, watch the number. If
routing is actually fine and the *assertion* is wrong, relax the sample.

## Reading an outcome result

```bash
uv run evals-pass-fail   # PASS/FAIL per sample: gating scorers + token budget
make eval-viewer         # the transcript — every tool call, file read, judge note
```

Two independent signals: **outcome** (did the gating scorers pass) and **cost**
(observed tokens vs `baseline × 1.5`). A sample can pass on outcome yet regress
on tokens — that's still a signal worth reading.

When something's red, in order:

1. **Transcript first.** If the agent didn't read the skill you expected, the
   prompt-or-routing is the bug, not the skill content.
2. **Scorer second.** If the agent did the right thing but a scorer failed,
   reproduce outside the sandbox — e.g. a CPT failure: `cd
   evals/scenarios/<id>/cpt-verifier && mvn test` (the Surefire XML names the
   assertion).
3. **Flake check.** Re-run with `--epochs 3` (`ARGS="--epochs 3"`) before
   treating one failure as a regression. The gate reduces epochs by mean, so a
   sample must pass *every* epoch to stay green — a flaky 2/3 reduces to 0.67 and
   fails, which is the signal.
4. **Compare arms.** Both arms failing ⇒ not a skill problem. Both passing ⇒ the
   skill may not be earning its keep.

## Adding a trigger eval

Edit `evals/skills/<skill>/triggers.py` — a thin `@task` that inlines its
samples and calls `build_trigger_eval`:

```python
"""Trigger eval for camunda-feel — does this prompt route here?"""
from pathlib import Path
from inspect_ai import Task, task
from core.triggers import Negative, Positive, build_trigger_eval

@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,                 # the skill = this directory
        positive=[                                   # prompts that SHOULD load it
            Positive("gateway-condition",
                     "What FEEL expression takes a flow only when amount > 1000?"),
        ],
        negative=[                                   # prompts that should route elsewhere
            Negative("author-process", "Design a BPMN process for invoice approval.",
                     should_load=["camunda-bpmn"]),  # optional: where it routes instead
        ],
    )
```

The target skill is implicit: every `Positive` asserts `should_load=[<skill>]`,
every `Negative` asserts `should_not_load=[<skill>]` — never repeat it. Ids are
auto-prefixed `pos-` / `neg-`. Optional extra guards: `Positive(...,
should_not_load=[...])` keeps a sibling out on a positive prompt;
`Negative(..., should_load=[...])` names where it should route instead. Two more
`build_trigger_eval` kwargs: `excluded_skills=[...]` hides skills from the
routing catalog (e.g. hide the meta-router from a leaf skill's trigger);
`also_run_when_changed=[...]` widens the CI changed-skills filter (no runtime
effect). Run it: `make eval-triggers SKILL=camunda-feel`.

## Adding an outcome eval

An `outcomes.py` with a module-level `METADATA` and an `@task`. Single-skill →
`skills/<skill>/`; cross-skill → `scenarios/<id>/`. Copy the closest existing one:

- judge-scored, text-only → `skills/camunda-development/outcomes.py`
- deterministic + cluster → `skills/camunda-feel/outcomes.py`
- deploy + lint + CPT → `scenarios/rocket-launch/outcomes.py`

```python
METADATA = EvalMetadata(
    skills=["camunda-feel"],  # CI changed-skills filter; also what without_skill drops
    # without_skill_excludes="all",  # override: drop every skill (meta-routers, scenarios)
    # max_sandboxes=10,  # parallelize samples; omit (=1) for cluster evals
)

@task
def camunda_feel(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=[...],
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[feel_evaluates_to(), assert_skill_loaded("camunda-feel", gating=False)],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
    )
```

- **Scorers** (compose any in `scorer=[...]`): judge
  `model_graded_qa(instructions=...)` against a per-sample rubric in
  `Sample.target`; deterministic `feel_evaluates_to()`, `bpmn_lint_clean()`,
  `process_deployed_on_cluster(id)`, `cpt_scorer(...)`; diagnostic
  `assert_skill_loaded(target, gating=False)`.
- **Sandbox** — pick by what the scorers need: `compose-advisory.yaml` (no
  cluster), `compose-with-c8ctl.yaml` (live cluster),
  `compose-cpt-verifier.yaml` (cluster + CPT). Anything bespoke (e.g. WireMock):
  drop a `compose.yaml` next to the `outcomes.py` and `include:` an archetype.
- **`max_sandboxes`** (default 1) caps parallel samples — each sample is its own
  sandbox. Keep 1 for cluster-backed evals (concurrent JVMs starve each other);
  raise it for a no-cluster eval.
- **`without_skill_excludes`** (defaults to `skills`) — the load-bearing skill(s)
  the `without_skill` arm drops, so it measures what the skill adds. Set `"all"`
  to drop every skill (meta-routers and cross-skill scenarios, where the value
  only shows once the whole catalog is gone).

Run it: `make eval-outcomes TARGET=skills/camunda-feel`. No workflow edit — CI
picks it up from `metadata.skills`.

**Authoring rules:** name the *failure mode*, not the skill
(`dmn-collect-ordering`, not `dmn-test`). Edge cases are *samples*, not separate
evals — add `Sample(id="edge-…", …)` (or `Positive`/`Negative`) entries.

## Maintaining baselines

Committed baselines are regenerated **on CI against the canonical model** (label
a PR `evals:regen-baselines` — see [`ci.md`](ci.md)), because token counts are
model-specific. Locally you can rewrite one for a quick check, but the numbers
reflect whatever model you ran:

```bash
make eval-outcomes TARGET=skills/camunda-feel        # produce a fresh run
make eval-baseline TARGET=skills/camunda-feel        # rewrite the baseline from it
git diff evals/skills/camunda-feel/outcomes_baseline.json   # review before committing
```

- Regenerate only after an **intentional** behaviour change — review the token
  diff and ask whether the new budget is what you meant.
- **Never** blanket-regen, and **never** to "make CI green." If the outcome is
  failing and the skill is supposed to work, fix the skill — the baseline is a
  cost ceiling, never the outcome bar.
- Only passing samples get an entry; a failed one keeps its old reference (or
  none) until it passes.

## Housekeeping

- Before committing any Python under `evals/`, run `uv run ruff format .` (from
  `evals/`) and commit what it reformats — including pre-existing drift. Keep the
  tree formatted; don't revert the churn.
- Run `make lint` outside any command sandbox (it hits `docs.camunda.io` for
  link health).
- `.eval` logs are CI artifacts, not source — `evals/logs/` is gitignored. Don't
  commit them.
