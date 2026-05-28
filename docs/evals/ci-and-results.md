# Eval suite — CI & results

How evals run in CI, what the PR comment looks like, and how to debug
a failure from a CI artifact.

## Workflows

| Workflow | Trigger | Scope |
|---|---|---|
| `.github/workflows/lint.yml` (existing) | PR touching `skills/**` or `.waza.yaml` | `waza check` only |
| `.github/workflows/eval.yml` | `evals:run` label on a PR (maintainer-applied), or the Actions tab (`workflow_dispatch`) | Runs scenarios where `metadata.skills ∩ changed-skills ≠ ∅`; posts a PR comment. **Non-blocking** (signal only). |
| `.github/workflows/eval-nightly.yml` | **`workflow_dispatch` only** (cron re-enabled in a follow-up) | Nightly schedule on `main`; runs every scenario |

`eval.yml` is **opt-in and maintainer-gated**, not automatic on every
PR:

- An `authorize` job checks the triggering actor's permission via
  `repos.getCollaboratorPermissionLevel`; only `admin` / `maintain` /
  `write` proceed. (`workflow_dispatch` already requires write access.)
- It runs only when a maintainer adds the **`evals:run`** label (and
  re-runs on subsequent pushes while the label is present). Removing
  the label stops further runs.
- It uses the `pull_request` event (not `pull_request_target`), so a
  fork PR never gets the AWS secrets — model runs only happen on
  maintainer branches in this repo.

Scenario selection is automatic from `metadata.skills` (resolved by
`evals-list --changed-skills`); no separate workflow matrix to keep in
sync. The run is non-blocking — keep it out of required status checks;
the PR comment is the signal.

## Scenario selection

There's no tier concept today. PR runs intersect `metadata.skills`
with the changed skills (so a PR runs only the scenarios it can
affect); nightly runs every scenario. Adding a scenario needs no
workflow change — selection falls out of `metadata.skills`. A
tier/scheduling split can be reintroduced if and when the scenario
set grows enough to need it.

## PR comment

One rolling comment per PR: a `find-comment` step locates the previous
one by a hidden marker (`<!-- camunda-skills-eval-comment -->`) and
`create-or-update-comment@v4` replaces it in place — not stacked.

Shape (rendered by `evals/src/scripts/summarize.py`): a summary table
with a per-scenario verdict (✅ pass / ⚠️ check — non-gating),
`pass_rate`, and a baseline cell (how many token/duration bands landed
in range), followed by a collapsible block per scenario carrying the
full `evals-pass-fail` breakdown (per-sample scorer table + per-band
observed-vs-range deltas):

```
### 🧪 Eval results

_Non-blocking signal — reports outcome + baseline deltas; does not gate merge._

| Scenario | Arm | Verdict | pass_rate | Baseline |
|---|---|---|---|---|
| c8ctl-bootstrap | with_skill | ✅ pass | 100% | ✅ 2 bands in |
| rocket-launch   | with_skill | ✅ pass | 100% | 🔴 1/2 bands out |

<details><summary>rocket-launch (with_skill)</summary>

  …per-sample scorer table + baseline gate (observed vs band)…
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
├── <scenario-id>-with-skill-<timestamp>.eval
├── <scenario-id>-without-skill-<timestamp>.eval
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
   call. Cross-reference with the scenario's verifier (e.g., for CPT,
   the Surefire XML names the assertion that failed).
5. To reproduce locally:
   ```bash
   make eval SCENARIO=<id>
   ```
   The harness is reproducible — same image, same compose, same
   prompts. Local failures should match CI failures modulo model
   non-determinism (re-run with Inspect's `--epochs 3` to check flake).

## Credentials & secrets

The suite is model-agnostic — the model id is just configuration:

- **Local** defaults to `anthropic/claude-sonnet-4-6` (the Makefile's
  `MODEL`); export `ANTHROPIC_API_KEY`. Override per run with `MODEL=…`.
- **CI** defaults to `bedrock/global.anthropic.claude-sonnet-4-6`.
  Change it for CI in one place — the `EVAL_MODEL` repo variable — with
  no code edit.

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
scenario. To smoke-test the CI provider (Bedrock) locally, pass the
same model id with your AWS credentials in the environment:

```bash
AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_DEFAULT_REGION=us-east-1 \
  make eval SCENARIO=dev-routing MODEL=bedrock/global.anthropic.claude-sonnet-4-6
```

`dev-routing` is the cheapest smoke — advisory, no cluster boot, one
sample (the `eval` target already passes `--max-samples 1` and
`-T agent=react`). A clean exit with a scored sample confirms the
credentials and model resolve. Drop the `MODEL=` override to use the
local default (`anthropic/claude-sonnet-4-6` + `ANTHROPIC_API_KEY`).

## Cost controls

- Each sample runs once by default. Use Inspect's `--epochs` only with
  evidence of flake — don't pay for repeats by default.
- `time_limit` per task is set via Inspect's task-level config.
  Per-scenario in `task.py`.
- Compose `deploy.resources.limits` cap memory/CPU per container.
  Adjust the relevant `evals/sandboxes/compose-*.yaml` if a scenario
  legitimately needs more.
- The PR comment surfaces token / duration band excursions. If a
  scenario systematically blows its band, that's a regression signal —
  investigate before regenerating the baseline.

## Not yet built

Deferred to follow-ups — open them as PRs when their trigger fires:

- Cross-harness comparison matrix (run the suite under multiple agent loops)
- Automated assertion-hygiene check (catch always-pass / always-fail scorers)
- A/B comparison between skill versions
- Static-export Inspect view to GitHub Pages
