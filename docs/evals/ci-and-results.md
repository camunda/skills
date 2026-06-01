# Eval suite — CI & results

How evals run in CI, what the PR comment looks like, and how to debug
a failure from a CI artifact.

## Workflows

| Workflow | Trigger | Scope |
|---|---|---|
| `.github/workflows/lint.yml` (existing) | PR touching `skills/**` or `.waza.yaml` | `waza check` only |
| `.github/workflows/eval.yml` | `evals:run` / `evals:run-all` / `evals:compare` label on a PR, or the Actions tab (`workflow_dispatch`) | Runs affected (or all) eval targets; posts a PR comment. **Non-blocking** (signal only). |
| `.github/workflows/eval-nightly.yml` | **`workflow_dispatch` only** (cron re-enabled in a follow-up) | Runs every target; uploads logs as artifacts |

`eval.yml` is **opt-in and maintainer-gated by labels**, not automatic
on every PR. There's no separate authorization job: only collaborators
with **triage or higher** can label a PR, so the label *is* the gate,
and `workflow_dispatch` already requires write access. Because it uses
the `pull_request` event (not `pull_request_target`), a fork PR never
receives the AWS secrets — model runs only happen on branches in this
repo.

Three labels select the scope (re-runs on each push while the label is
present; remove it to stop):

- **`evals:run`** — targets whose skills intersect the changed skills
  (`metadata.skills ∩ changed-skills ≠ ∅`, resolved by
  `evals-list --changed-skills`); the targeted PR signal.
- **`evals:run-all`** — every target, to integration-test the whole
  suite against the branch.
- **`evals:compare`** — also run the `without_skill` arm of result and
  scenario targets, to surface the with-vs-without skill delta.

The model is fixed to a single id via the `EVAL_MODEL` repo variable
(default a Bedrock Claude). A multi-model matrix would add a `model`
axis — not done yet.

`workflow_dispatch` accepts two inputs: `target` (substring filter over
target ids) and `compare` (boolean — run the `without_skill` arm too).

### Running the full suite on a branch

Two ways, depending on whether you want the PR comment:

- **`evals:run-all` label** on the PR — runs every target through the
  same pipeline and posts the comment.
- **Dispatch `eval-nightly.yml`** (Actions tab → Run workflow → pick the
  branch) — runs every target and uploads logs as artifacts, no
  comment. Equivalent to a manual nightly against that ref.

### Jobs

`detect` → `run` → `summarize`. `detect` expands the label/inputs into
a list of run-specs (one per target × arm); `run` is a matrix over those
specs; `summarize` collects the logs into the PR comment.

### What goes red

The `run` job has two failure modes, both surfaced as a red ❌ check:

- **Run breakage** — the run step (`make eval-…`) exits non-zero on a
  sandbox/auth/exception failure. A target that merely scores low does
  *not* red here (Inspect exits 0 on a completed run).
- **Quality gate** — the `Gate (evals-pass-fail)` step reds when a
  sample misses its per-sample outcome threshold or exceeds its token
  budget (`baseline × 1.5`). The gate step is **skipped for the
  `without_skill` arm** — that arm is a comparison, not a quality bar.

Both are **non-blocking as long as this workflow stays out of required
status checks** — a red is a signal to look, not a merge block, and the
PR comment carries the detail.

## Target selection

There's no tier concept. PR runs intersect `metadata.skills` with the
changed skills (so a PR runs only the targets it can affect); nightly
runs every target. `evals-list --json` emits one entry per target —
`{id, kind, skills, path, task, args}`, where `id` is e.g.
`trigger:camunda-feel`, `result:camunda-feel`, or
`scenario:rocket-launch` and `kind` is `trigger | result | scenario`.
Adding a target needs no workflow change — selection falls out of
`metadata.skills` (and, for triggers, `target_skill`).

## PR comment

One rolling comment per PR: a `find-comment` step locates the previous
one by a hidden marker (`<!-- camunda-skills-eval-comment -->`) and
`create-or-update-comment@v4` replaces it in place — not stacked.

Shape (rendered by `evals/src/scripts/summarize.py`): a summary table
keyed by eval and arm with an outcome verdict (✅ pass / ⚠️ check —
non-gating) and a token-budget cell (observed vs `baseline × 1.5`),
plus a "Skill impact" section showing the with-vs-without delta when the
`without_skill` arm ran, followed by a collapsible block per eval
carrying the full `evals-pass-fail` breakdown (per-sample scorer table +
token-budget deltas):

```
### 🧪 Eval results

_Non-blocking signal — reports outcome + token budget; does not gate merge._

| Eval | Arm | Outcome | Token budget |
|---|---|---|---|
| result:camunda-feel | with_skill | ✅ pass | ✅ within |
| scenario:rocket-launch | with_skill | ✅ pass | 🔴 over budget |

#### Skill impact (with vs without)

| Eval | with_skill | without_skill |
|---|---|---|
| result:camunda-feel | ✅ pass | ⚠️ fail |

<details><summary>scenario:rocket-launch (with_skill)</summary>

  …per-sample scorer table + token-budget gate (observed vs baseline × 1.5)…
</details>
```

The collapsible block is the same text `evals-pass-fail` prints, so the
comment and the CLI never drift. The comment is a summary; the
trajectory viewer is the debugger (see below).

## Artifacts

Every workflow run uploads `.eval` logs as a workflow artifact
named `eval-logs-<sha>`. Retention defaults to GitHub's actions
artifact retention (90 days unless tightened in repo settings).

Artifact contents:

```
evals/logs/
├── <target-id>-with-skill-<timestamp>.eval
├── <target-id>-without-skill-<timestamp>.eval
└── summary.json
```

## Debugging a failure from a CI artifact

1. Download the artifact from the Actions tab (or via `gh run
   download <run-id>` locally).
2. Extract to a local directory.
3. Open the trajectory viewer:
   ```bash
   uv run inspect view path/to/extracted-logs/
   ```
   The UI is at `http://localhost:7575`.
4. Drill into the failing sample. The transcript shows every tool
   call. Cross-reference with the eval's scorers (e.g., for CPT, the
   Surefire XML names the assertion that failed).
5. To reproduce locally, run the matching target:
   ```bash
   make eval-trigger SKILL=<name>   # trigger
   make eval-result  SKILL=<name>   # per-skill result
   make eval         SCENARIO=<id>  # cross-skill scenario
   ```
   The harness is reproducible — same image, same compose, same
   prompts. Local failures should match CI failures modulo model
   non-determinism (re-run with Inspect's `--epochs 3` to check flake).

## Credentials & secrets

The suite is model-agnostic — the model id is just configuration:

- **Local** defaults to `anthropic/claude-sonnet-4-6` (the Makefile's
  `MODEL`); export `ANTHROPIC_API_KEY`. Override per run with `MODEL=…`.
- **CI** defaults to `anthropic/bedrock/global.anthropic.claude-sonnet-4-6`
  (Inspect's `anthropic` provider with the `bedrock/` qualifier). Change
  it for CI in one place — the `EVAL_MODEL` repo variable — no code edit.

For the CI default (Bedrock), `eval.yml` reads:

| Kind | Name | Purpose |
|---|---|---|
| Secret | `AWS_ACCESS_KEY_ID` | model auth |
| Secret | `AWS_SECRET_ACCESS_KEY` | model auth |
| Variable | `AWS_DEFAULT_REGION` | region (defaults to `us-east-1`) |
| Variable | `EVAL_MODEL` | optional — overrides the CI model id |

Add secrets under **Settings → Secrets and variables → Actions →
Secrets**, variables under the **Variables** tab. Because the workflow
triggers on `pull_request` (not `pull_request_target`), these secrets
are exposed only to runs on branches in this repo — never to fork PRs.
If you point `EVAL_MODEL` at a non-AWS provider, swap the credential
env in the workflow's run step for that provider's.

### Local smoke test

Build the images once (`make eval-images`), then run the cheapest
eval. To smoke-test the CI provider (Bedrock) locally, pass the same
model id with your AWS credentials in the environment:

```bash
AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_DEFAULT_REGION=us-east-1 \
  make eval-trigger SKILL=camunda-feel MODEL=anthropic/bedrock/global.anthropic.claude-sonnet-4-6
```

A trigger eval is the cheapest smoke — no cluster boot. The judge
result eval `make eval-result SKILL=camunda-development` is the next
step up (also no cluster). A clean exit with a scored sample confirms
the credentials and model resolve. Drop the `MODEL=` override to use the
local default (`anthropic/claude-sonnet-4-6` + `ANTHROPIC_API_KEY`).

## Cost controls

- Each sample runs once by default. Use Inspect's `--epochs` only with
  evidence of flake — don't pay for repeats by default.
- `time_limit` per task is set via Inspect's task-level config, in the
  eval's `task.py`.
- Compose `deploy.resources.limits` cap memory/CPU per container.
  Adjust the relevant `evals/sandboxes/compose-*.yaml` if an eval
  legitimately needs more.
- The PR comment surfaces token-budget excursions (observed vs
  `baseline × 1.5`). If an eval systematically blows its budget, that's a
  regression signal — investigate before regenerating the baseline.

## Not yet built

Deferred to follow-ups — open them as PRs when their trigger fires:

- Multi-model matrix (add a `model` axis to the run matrix)
- Cross-harness comparison matrix (run the suite under multiple agent loops)
- Automated assertion-hygiene check (catch always-pass / always-fail scorers)
- A/B comparison between skill versions
- Static-export Inspect view to GitHub Pages
