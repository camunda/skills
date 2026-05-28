# Eval suite — scenarios (how-to)

How to read, maintain, debug, and add scenarios. For the "why" (sandbox
model, baseline semantics, harness choice), see
[`concepts.md`](concepts.md).

## Anatomy of a scenario

A scenario lives under `evals/scenarios/<slug>/`:

```
evals/scenarios/rocket-launch/
├── task.py                # @task + METADATA — the canonical contract
├── baseline.json          # expected pass-rate, per-sample token + duration bands
└── cpt-verifier/          # used when the scorer list includes cpt_scorer(...)
    ├── pom.xml            # Spring CPT (camunda-process-test-spring) + remote-runtime
    └── src/test/
        ├── java/.../RocketLaunchIT.java
        └── resources/application.yml   # camunda.process-test.runtime-mode: remote
```

`cpt-verifier/` is present only for scenarios whose scorer list
includes `cpt_scorer(...)`. A scenario that hands the agent a starting
file (e.g. "fix this broken BPMN") can keep that file alongside
`task.py` and reference it from the prompt.

## The `task.py` metadata contract

A Pydantic-typed `METADATA: ScenarioMetadata` at the top of each
`task.py` is the scenario contract. No YAML sidecar.
`core.registry` imports each `task.py`, reads `METADATA`, and the
model enforces the schema (`extra="forbid"` catches typos at load
time).

Fields (see `evals/src/core/metadata.py` for the model):

| Field | Type | Meaning |
|---|---|---|
| `skills` | `list[str]` | CI-orchestration only — drives the PR path-filter (a PR touching `skills/<X>/` runs scenarios where `X in metadata.skills`) and documents the load-bearing dependencies. Does **not** restrict the skill tool surface at runtime. |
| `baseline` | `BaselineConfig` | `{ exclude }` — which skills the `without_skill` arm drops (see `concepts.md`) |

The scenario id is the directory name; no `id` field on the model.
The sandbox compose file is declared explicitly on `Task(sandbox=...)`
per scenario; no `image` field on the model either. The scorer list
also lives on the `Task`; the metadata doesn't duplicate it (one
source of truth — read `Task(scorer=...)` to see what a scenario
checks).

Example:

```python
from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR

METADATA = ScenarioMetadata(
    skills=["camunda-bpmn", "camunda-process-mgmt"],
    baseline=BaselineConfig(exclude="all"),
)

@task
def rocket_launch() -> Task:
    return Task(
        dataset=[
            Sample(id="happy", input="…"),
            Sample(id="edge", input="…"),
        ],
        solver=...,
        scorer=...,
        sandbox=("docker", str(SANDBOXES_DIR / "compose-cpt-verifier.yaml")),
        metadata=METADATA.model_dump(),
    )
```

Sandbox archetypes live in `evals/sandboxes/`:
`compose-base.yaml`, `compose-with-c8ctl.yaml`,
`compose-cpt-verifier.yaml`. A scenario that needs custom infra
(e.g. WireMock) can drop in its own `compose.yaml` and reference it
directly. CI consumers (`evals-list`, `evals-summarize`, the
workflow filter) read the metadata directly — don't put configuration
anywhere else.

## How to add a new scenario

1. **Pick a slug** that names the *failure mode* the scenario
   catches, not the skill it exercises
   (`dmn-collect-ordering` > `dmn-test`). Must match
   `^[a-z][a-z0-9-]*$` (the registry enforces this).

2. **Copy the closest existing scenario**:
   ```bash
   cp -r evals/scenarios/rocket-launch evals/scenarios/<your-slug>
   ```

3. **Edit `task.py`** — update `METADATA`, prompt(s), and the sample
   list. Start with one happy path + one edge case; add more as
   failures surface (the design supports N samples).

4. **Write the verifier**:
   - CPT: edit `cpt-verifier/src/test/java/.../*IT.java` (Spring CPT,
     remote-runtime — see `rocket-launch/cpt-verifier/` for the
     reference shape)
   - Exit-code: write the assertion inline in the scenario's `task.py`
     as a small `@scorer` (see `c8ctl-bootstrap/task.py`)
   - Transcript: use `assert_tool_called` / `assert_skill_loaded` from
     `evals/src/scorers/transcript.py`
   - Lint: `bpmn_lint_clean()` from `scorers/lint.py` (BPMN);
     `form_lint_clean()` (forms — once vendored)
   - LLM judge: for free-form answer correctness use Inspect's
     built-in `model_graded_qa` with a per-sample rubric in
     `Sample.target` (see `dev-routing/task.py`) — no custom judge
     scorer is shipped.

5. **Run locally** to confirm it boots:
   ```bash
   make eval SCENARIO=<your-slug>
   ```

6. **Generate the baseline** once the scenario behaves correctly:
   ```bash
   make eval-baseline SCENARIO=<your-slug>
   ```
   Review the diff in `baseline.json` before committing.

7. **No workflow edit needed.** PR inclusion is automatic from
   `metadata.skills` — `eval.yml`'s `detect-scenarios` job intersects
   the changed skills with each scenario's `metadata.skills` via
   `evals-list --changed-skills`. (CI is currently
   `workflow_dispatch`-only; once credentials land, the path-filter
   path turns on without per-scenario workflow edits.)

## Edge cases

Each scenario starts with **1 happy + 1 edge case** but the design is
**N edge cases per scenario**. Inspect's native sample-list shape
supports this directly; the `id` field distinguishes them in the
trajectory viewer and PR comment.

Edge-case categories (add as they surface from real failures —
**don't pre-fabricate**):

- Ambiguous prompt
- Malformed input
- Version-floor edge (8.8 vs 8.9 features)
- Adversarial user (asks for an anti-pattern)
- Large-input

If you find yourself inventing edge cases, stop. The cost-effective
edge case is the one that already broke.

## How to debug a failure

1. **Read the transcript first.** `.eval` artifacts contain every
   tool call and file read:
   ```bash
   uv run inspect view evals/logs/
   # opens http://localhost:7575
   ```
   In CI: download the `.eval` artifact from the workflow run, then
   `uv run inspect view <downloaded-dir>` locally.

2. **Reproduce the verifier outside the sandbox.** The verifier's
   container is reproducible. For a CPT failure, `cd
   evals/scenarios/<id>/cpt-verifier && mvn test` runs the same test
   the verifier container ran. Surefire XML is at `target/surefire-reports/`.

3. **Re-run with more epochs to check flake**:
   ```bash
   uv run inspect eval evals/scenarios/<id>/task.py --epochs 3
   ```
   `--epochs` is Inspect's own flag (repeat each sample N times). If
   pass-rate is consistent at 1/3 or 3/3, the result is the result.
   If it bounces between runs, the scenario is flaky.

4. **Compare with-skill vs without-skill arms.** A scenario where
   both arms fail equally suggests the skill isn't the issue (or the
   prompt is bad). A scenario where both pass equally suggests the
   skill isn't earning its keep (or the model already knows this from
   training — drop the scenario or strengthen it).

## How to regenerate baselines safely

`make eval-baseline SCENARIO=<id>` rewrites `baseline.json` from the
last run. Never blanket-regen without diff review:

```bash
make eval-baseline SCENARIO=rocket-launch
git diff evals/scenarios/rocket-launch/baseline.json
# review the diff before committing
git add evals/scenarios/rocket-launch/baseline.json
git commit -m "feat(evals): refresh baseline for rocket-launch after …"
```

When to regenerate:
- After an intentional behaviour change (the new pass-rate / token
  band is the new normal)
- After adding or removing a sample (the new sample needs a band)

When **not** to regenerate:
- After a flaky run — diagnose the flake first
- After a regression — fix the regression, don't paper over it
- "Just to update everything" — never. Per-scenario, with review.

## Assertion hygiene checklist

Run through this before merging a scenario change:

- [ ] No always-pass — if pass_rate has been 1.0 for the last 50
      runs, the assertion isn't catching anything
- [ ] No always-fail — same logic, inverse
- [ ] Edge cases differ meaningfully from happy path — not just
      rewordings
- [ ] Without-skill arm actually fails (or has materially worse
      tokens/duration) — if the skill makes no difference, the
      scenario isn't proving anything

An automated hygiene check is a planned follow-up. Until then,
self-review.
