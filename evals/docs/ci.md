# Eval suite — CI

How evals run in CI, the PR comment, and how to debug from a CI artifact. For
the local loop see [`runbook.md`](runbook.md); for the model see
[`concepts.md`](concepts.md).

## A skill-change PR, end to end

1. **Iterate locally** (see [`runbook.md`](runbook.md)).
2. **Open the PR.** Nothing runs automatically — evals are opt-in and
   maintainer-gated by label.
3. **A maintainer adds `evals:run`** — runs the targets your change can affect,
   on the `with_skill` arm, gated against the committed baseline, and posts a
   rolling comment.
4. **Read it** — the PR comment for the verdict, the run's job summary for token
   usage, the trajectory viewer for a failing sample.
5. **Occasionally** add `evals:compare` (does the skill earn its keep — the
   with-vs-without delta) or `evals:run-all` (whole-suite check).
6. **Intentional behaviour change that moved tokens?** Label
   `evals:regenerate-baselines` — CI re-runs the outcome evals against the canonical
   model and commits refreshed baselines to the branch, for you to review in the
   diff. Never regenerate to make CI green.

## Workflows

| Workflow | Trigger | Scope |
|---|---|---|
| `lint.yml` | PR touching `skills/**` or `.waza.yaml` | `waza check` only |
| `eval.yml` | `evals:run` / `evals:run-all` / `evals:compare` label, or the Actions tab | Affected (or all) targets; posts the PR comment. **Non-blocking.** |
| `eval-nightly.yml` | `workflow_dispatch` only (cron re-enabled in a follow-up) | Every target; uploads logs as artifacts |
| `eval-baseline.yml` | `evals:regenerate-baselines` label, or the Actions tab | Re-runs outcome evals, regenerates baselines, commits them to the branch |

**Gating is the label.** Only collaborators with triage or higher can label a
PR, and `workflow_dispatch` requires write access — so there's no separate
authorization job. Because the workflows use `pull_request` (not
`pull_request_target`), a fork PR never receives the AWS secrets: model runs only
happen on branches in this repo.

## Labels

Labels make two **orthogonal** choices — *scope* and *arms* — and re-run on each
push while present (remove to stop):

- **`evals:run`** — targets whose `metadata.skills` intersect the changed skills
  (the everyday signal).
- **`evals:run-all`** — every target (whole-suite / harness check).
- **`evals:compare`** — *also* run the `without_skill` arm of outcome evals.
  Without it, outcome evals run `with_skill` only.

| You want to… | Label(s) | Runs | Gated vs baseline? |
|---|---|---|---|
| Check the skills your PR touched | `evals:run` | affected, `with_skill` | ✅ |
| Check the whole suite | `evals:run-all` | every target, `with_skill` | ✅ |
| See what a skill *adds* | either + `evals:compare` | adds `without_skill` | `with_skill` ✅ · `without_skill` ❌ |

`workflow_dispatch` accepts `target` (substring filter over target ids) and
`compare` (run the second arm).

## Target selection

No tiers. `evals-list --json` emits one entry per target —
`{id, kind, skills, path, task, args, max_sandboxes}` — where `id` is e.g.
`trigger:camunda-feel`, `skill:camunda-feel`, or `scenario:rocket-launch`, and
`kind` is `trigger | outcome`. PR runs intersect `metadata.skills` with the
changed skills; nightly runs everything. Adding a target needs no workflow change.

## Jobs and what goes red

`detect` → `build-images` → `run` (matrix over targets × arms) → `summarize`.
`build-images` builds the three sandbox images **once** per run (from
`evals/sandboxes/docker-bake.hcl`, with a `type=gha` layer cache so Docker Hub
base images are pulled at most once across runs), then ships them to the matrix
as a one-day artifact that each outcome job restores with `docker load` — no
per-job rebuilds, no registry, nothing published. It's skipped on a
triggers-only run (no sandbox targets). The `run` job has two red ❌ modes:

- **Run breakage** — the run step exits non-zero (sandbox/auth/exception). A
  target that merely *scores low* does not red here (Inspect exits 0).
- **Quality gate** — `evals-pass-fail` reds when a sample misses its outcome
  threshold or exceeds its token budget (`baseline × 1.5`). Skipped for the
  `without_skill` arm (comparison, not a bar).

Both are **non-blocking** as long as the workflow stays out of required status
checks — a red is a signal to look, and the PR comment carries the detail.

## The PR comment & job summary

`evals-summarize` renders one report to two surfaces:

- **PR comment** (pull requests) — the lean render. One rolling comment: a hidden
  marker locates the prior one and replaces it in place.
- **Job summary** (every run) — the `--detail` render, adding a per-eval token
  column (total + `[I/CW/CR/O]` split). Also saved into the artifact as
  `summary.md`.

Shape: a headline verdict, model + run-wide token usage, an outcome table
(verdict + observed tokens vs `baseline × 1.5`, with a `🔴` when over ceiling and
turns/tool-call deltas under `--detail`), a trigger routing table, and a "Skill
impact" delta when the `without_skill` arm ran. In CI each eval name links to its
source on the run's commit. The report is a summary — the trajectory viewer is
the debugger; `evals-pass-fail` gives the per-sample scorer + budget breakdown.

## Regenerating baselines

`eval-baseline.yml` re-records each outcome eval's token baseline from a fresh
run against the canonical `EVAL_MODEL` (median per sample, passing samples only):

- **On a PR** — label `evals:regenerate-baselines`. CI re-runs the outcome evals at
  `--epochs 3` (so the reference is a median, not a single-shot outlier),
  regenerates the baselines, and **commits them to the PR branch**. The diff is
  your review surface.
- **After merge** — dispatch from the Actions tab on a branch; inputs `target`
  (substring, blank = all) and `epochs`. It **refuses the default branch** —
  regenerate for `main` goes through a PR.

It **never** runs on push/synchronize: auto-regenerate would rewrite the very
yardstick the cost gate checks against, so a regression would silently become the
new normal.

## Artifacts & debugging from CI

Each run publishes one consolidated artifact `eval-logs-<sha>` — every `.eval`
log plus the rendered `summary.md` (30-day retention on PRs, 14 nightly). To
debug a failure:

```bash
gh run download <run-id>                       # or download from the Actions tab
uv run inspect view path/to/extracted-logs/    # trajectory viewer, localhost:7575
```

Drill the failing sample; cross-reference its scorers (for CPT, the Surefire XML
names the assertion). Reproduce locally with the matching `make run-trigger-evals
SKILL=<name>` / `make run-outcome-evals TARGET=<dir>` — same image, compose, and
prompts, modulo model non-determinism (`--epochs 3` to check flake).

## Credentials & secrets

The model id is configuration. CI defaults to
`anthropic/bedrock/global.anthropic.claude-sonnet-4-6` (Inspect's `anthropic`
provider with the `bedrock/` qualifier), switchable in one place — the
`EVAL_MODEL` repo variable. For the Bedrock default the workflows read:

| Kind | Name | Purpose |
|---|---|---|
| Secret | `AWS_ACCESS_KEY_ID` | model auth |
| Secret | `AWS_SECRET_ACCESS_KEY` | model auth |
| Variable | `AWS_DEFAULT_REGION` | region (default `us-east-1`) |
| Variable | `EVAL_MODEL` | optional — overrides the CI model id |

Set these under **Settings → Secrets and variables → Actions**. Point
`EVAL_MODEL` at a non-AWS provider and swap the credential env in the run step.

## Cost controls

- Each sample runs once by default. Use `--epochs` only with evidence of flake.
- Per-task `time_limit` lives in the eval's `outcomes.py`; per-container
  memory/CPU caps in the relevant `evals/sandboxes/compose-*.yaml`.
- The PR comment surfaces token-budget excursions (observed vs `baseline × 1.5`)
  — a systematic blow-up is a regression signal; investigate before regenerating.

## Not yet built

Deferred follow-ups — opened as PRs when their trigger fires, not pre-fabricated:

- **Re-enable the nightly cron** (currently `workflow_dispatch`-only).
- **Multi-model matrix** — add a `model` axis to the run matrix.
- **Cross-harness matrix** — run the suite under multiple agent loops once an
  Inspect bridge for a CLI harness exists.
- **Assertion-hygiene check** — flag always-pass / always-fail scorers.
- **A/B comparison** between skill versions; **static-export Inspect view** to
  GitHub Pages.
