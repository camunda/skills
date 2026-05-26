# Eval suite — scenarios (how-to)

How to read, maintain, debug, and add scenarios. For the "why" (sandbox
model, baseline semantics, harness choice), see
[`concepts.md`](concepts.md).

## Anatomy of a scenario

A scenario lives under `evals/src/scenarios/<slug>/`:

```
evals/src/scenarios/rocket-launch/
├── task.py                # @task + METADATA — the canonical contract
├── baseline.json          # expected pass-rate, token band, duration band
├── fixtures/              # input files the agent (or verifier) reads
│   └── RocketLaunch.bpmn  # for scenarios that hand the agent a starting file
└── cpt-verifier/          # Phase 2 — used when verifier="cpt" (or composite-incl-CPT)
    ├── pom.xml            # Spring CPT (camunda-process-test-spring) + remote-runtime
    └── src/test/
        ├── java/.../RocketLaunchIT.java
        └── resources/application.yml   # camunda.process-test.runtime-mode: remote
```

Files that may be absent depending on the verifier:
- `cpt-verifier/` — only for `verifier: "cpt"` scenarios
- `fixtures/` — only when the scenario hands the agent a starting file
  (e.g. "fix this broken BPMN" rather than "build it from scratch")

## The `task.py` metadata contract

A Pydantic-typed `METADATA: ScenarioMetadata` at the top of each
`task.py` is the scenario contract. No YAML sidecar.
`core.registry` imports each `task.py`, reads `METADATA`, and the
model enforces the schema (`extra="forbid"` catches typos at load
time).

Fields (see `evals/src/core/metadata.py` for the model):

| Field | Type | Meaning |
|---|---|---|
| `skills` | `list[str]` | Which skills this scenario exercises (controls path-filtered PR CI) |
| `epochs` | `int` | Default 1; 3 for trigger/judge-scored scenarios |
| `tier` | `"pr" \| "nightly" \| "release"` | When the scenario runs |
| `verifier` | `"cpt" \| "exit-code" \| "transcript" \| "judge" \| "composite"` | Phase 2 shape |
| `baseline` | `BaselineConfig` | `{ mode, exclude }` — comparison arm (see `concepts.md`) |

The scenario id is the directory name; no `id` field on the model.
The sandbox compose file is declared explicitly on `Task(sandbox=...)`
per scenario; no `image` field on the model either.

Example:

```python
from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR

METADATA = ScenarioMetadata(
    skills=["camunda-bpmn", "camunda-process-mgmt"],
    tier="pr",
    verifier="cpt",
    baseline=BaselineConfig(mode="without-skill", exclude=["camunda-bpmn"]),
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
   cp -r evals/src/scenarios/rocket-launch evals/src/scenarios/<your-slug>
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
   - Judge: use `judge_bpmn_quality()` / equivalent from
     `evals/src/scorers/llm_judge.py`. The rubric lives inline in
     that module (one-prompt + score regex); no separate Markdown
     file. Override `judge_model=` per scenario if you need a
     different judge.

5. **Run locally** to confirm it boots:
   ```bash
   make eval SCENARIO=<your-slug>
   ```

6. **Generate the baseline** once the scenario behaves correctly:
   ```bash
   make eval-baseline SCENARIO=<your-slug>
   ```
   Review the diff in `baseline.json` before committing.

7. **No workflow edit needed.** PR-tier inclusion is automatic from
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
   evals/src/scenarios/<id>/cpt-verifier && mvn test` runs the same test
   the verifier container ran. Surefire XML is at `target/surefire-reports/`.

3. **Re-run with more epochs to check flake**:
   ```bash
   uv run inspect eval evals/src/scenarios/<id>/task.py --epochs 3
   ```
   If pass-rate is consistent at 1/3 or 3/3, the result is the result.
   If it bounces between runs, the scenario is flaky — bump its `epochs`
   in metadata and set a pass-rate threshold in `baseline.json`.

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
git diff evals/src/scenarios/rocket-launch/baseline.json
# review the diff before committing
git add evals/src/scenarios/rocket-launch/baseline.json
git commit -m "feat(evals): refresh baseline for rocket-launch after …"
```

When to regenerate:
- After an intentional behaviour change (the new pass-rate / token
  band is the new normal)
- After bumping a scenario's `epochs`

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

`FOLLOWUP-EVAL-03` adds an automated hygiene cron. Until then,
self-review.
