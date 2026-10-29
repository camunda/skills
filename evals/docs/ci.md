# Eval suite — CI

How evals run in CI, the PR comment, and how to debug from a CI artifact. For
the local loop see [`runbook.md`](runbook.md); for the model see
[`concepts.md`](concepts.md).

## A skill-change PR, end to end

1. **Iterate locally** (see [`runbook.md`](runbook.md)).
2. **Open the PR.** Evals auto-run for PRs that touch skill/eval/harness files.
3. **Default run scope** is targets your change can affect, on the `with_skill`
   arm, gated against the committed baseline, with a rolling PR comment.
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
| `compatibility.yml` | Relevant PR paths, weekly schedule, or manual dispatch | Portability conformance plus deterministic Claude/Copilot smoke checks. |
| `eval.yml` | PR changes to skill/eval/harness paths, or the Actions tab (`evals:run-all` / `evals:compare` labels optional) | Affected (or all) targets; posts the PR comment. **Non-blocking.** |
| `eval-nightly.yml` | `workflow_dispatch` only (cron re-enabled in a follow-up) | Every target; uploads logs as artifacts |
| `eval-baseline.yml` | `evals:regenerate-baselines` label, or the Actions tab | Re-runs outcome evals, regenerates baselines, commits them to the branch |
| `eval-models.yml` | `workflow_dispatch` only (monthly cron commented out) | Outcome evals × several Copilot models via Copilot CLI; renders the [model comparison matrix](#model-comparison-matrix). **Informational, no gate.** |

Auto-runs come from `pull_request` path filters; labels are optional refinements
for scope/arms. `workflow_dispatch` still requires write access. Because the
workflow uses `pull_request` (not `pull_request_target`), fork PRs do not
receive model secrets.

## Labels

Labels are optional refinements and re-run on each push while present (remove
to stop):

- **`evals:run-all`** — every target (whole-suite / harness check).
- **`evals:compare`** — *also* run the `without_skill` arm of outcome evals.
  Without it, outcome evals run `with_skill` only.

| You want to… | Label(s) | Runs | Gated vs baseline? |
|---|---|---|---|
| Check the skills your PR touched | none (default) | affected, `with_skill` | ✅ |
| Check the whole suite | `evals:run-all` | every target, `with_skill` | ✅ |
| See what a skill *adds* | optional `evals:compare` | adds `without_skill` | `with_skill` ✅ · `without_skill` ❌ |

`workflow_dispatch` accepts `target` (substring filter over target paths) and
`compare` (run the second arm).

## Target selection

No tiers. `evals-list --json` emits one entry per target —
`{id, kind, skills, path, task, args, max_sandboxes}` — where `id` is e.g.
`trigger:camunda-feel`, `skill:camunda-feel`, or `scenario:rocket-launch`, and
`kind` is `trigger | outcome`.

PR target selection is a union:

- skill-driven selection (`metadata.skills ∩ changed_skills`) for product-skill edits
- exact eval-path selection for changed eval files (so an edit to
  `evals/skills/<skill>/outcomes.py` runs that target only)

Harness/framework edits (`evals/src`, sandboxes, workflow plumbing, Python
project files) still widen to all skills. Nightly runs everything.

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
run against the canonical `EVAL_MODEL` (median per sample). It fans the outcome
targets out across a matrix — one runner per target, like the run workflow — and
each job regenerates only its own baseline; a final job collects them into a
single commit. A baseline is **all-green or nothing**: a target whose run had any
failing or unscored sample regenerates nothing and keeps its committed baseline
(the job logs a warning), so a partial baseline never lands.

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

## Model comparison matrix

`eval-models.yml` answers "which model should we recommend for which skill?". It
runs the outcome evals through **GitHub Copilot CLI** — the harness users
actually run the skills in — once per Copilot model, so one enterprise licence
covers Claude, GPT, and Gemini models. Run it from the Actions tab (**🧪 Model
comparison matrix → Run workflow**):

| Input | Default | Meaning |
|---|---|---|
| `models` | `claude-sonnet-5.5,claude-opus-5.5,claude-haiku-5.5,gpt-6.1-sol,gemini-4-argon` | comma-separated Copilot model ids (`copilot --model`) — the matrix columns |
| `epochs` | `3` | repeat runs per sample, for steadier medians |
| `target` | _(all)_ | substring of the target path, e.g. `camunda-bpmn`, for a partial run |

**Model ids are per token.** The job token is billed to the org and governed
by the org's Copilot model policy, so its catalogue can differ from a personal
sign-in — ids that work in your own `copilot` session may be *not available*
in Actions. The *Check Copilot models* step (`evals-copilot-models --check`)
lists the models the job token can use in the job summary and fails the run
before any agent job starts if a requested id isn't among them (Copilot only
rejects a bad `--model` once a session starts, which would otherwise fan out
into jobs that each fail in seconds). If the catalogue can't be read it warns
and continues unverified. `auto` is always accepted. To check locally with
your own token: `COPILOT_GITHUB_TOKEN=$(gh auth token) uv run
evals-copilot-models --check <ids>`.

**Inspect limits.** Tasks size `message_limit` for Inspect-driven agents;
Copilot runs its own loop and its transcript is replayed afterwards, so model
mode lifts the message limit (`--message-limit 100000`) — otherwise a long
session's replay would be cut short. The task's `time_limit` still applies.
Runs stopped by any Inspect limit are counted in a note at the top of the
report and a *limits hit* column, and scored on what they produced.

**Failures are loud.** If runs error (an agent or sandbox failure rather than a
wrong answer), the summary opens with a banner and an **Errors** table of the
most common message per model, fully errored models get a warning annotation,
and *Build model matrix* fails when every run errored.

**How it runs.** `evals-build-matrix --models … --epochs …` emits one job per
outcome target × model with `-T agent=copilot_cli` (`evals/src/core/copilot_cli.py`).
Per sample, that agent installs Copilot CLI in the sandbox (`COPILOT_CLI_VERSION`
repo variable, default `latest`), copies in the arm's skills
(`COPILOT_SKILLS_DIRS`), runs `copilot -p --model <id> --allow-all --no-ask-user
--output-format json`, and replays its event stream into the Inspect transcript —
so the existing scorers and verifier phase are unchanged. Inspect runs with
`--model none`; only the LLM judge (camunda-development) calls a model through
Inspect, pinned to `EVAL_MODEL` via `--model-role grader=…`.

**Auth.** The run job's own `GITHUB_TOKEN` with `permissions: copilot-requests:
write` — no PAT or stored secret (the same pattern as `camunda/sdk-infra`'s agent
workflows). Requires the org policy *Allow use of Copilot CLI billed to the
organization*; usage is billed to the org. The token is job-scoped and expires
with the job. It reaches the sandbox only through an exec the eval log doesn't
record, and `--secret-env-vars` strips it from the agent's shell and redacts it
from output, so it never appears in the uploaded logs. `actionlint` doesn't know
the `copilot-requests` scope yet; `.github/actionlint.yaml` suppresses that.

**Output.** The job summary and the `model-matrix-<run-id>` artifact
(`model-matrix.md`, `model-matrix.json`, raw `.eval` logs; 90-day retention).
Per cell, over every sample×epoch run:

- **Pass rate** — every gating scorer passed; errored samples count as fails.
  The detail tables add **skill loaded** — how often the model loaded the skill
  under test (some models skip skills and then fail on schema details).
- **Linter attempts** — median validator runs (`c8ctl bpmn lint`, `dmnlint`,
  `node validate-form.cjs` or an inline `node -e` check against
  `@bpmn-io/form-json-schema`) until the first clean result, plus the share of
  runs that ever got clean. Read post-hoc from the transcript
  (`evals/src/core/lint_attempts.py`); `—` where the agent never validates.
  `--dry-run` ruleset checks don't count, and one tool call is one attempt. Only
  executed invocations count — matched on the tool actually run (through
  `xargs`, `find -exec`, and `npx`/`npm exec` wrappers), so heredoc bodies,
  quoted text, and package installs (`npm install dmnlint`) aren't runs. Output
  delivered later via Copilot's `read_bash` is attributed to the run that
  started it.
  A call running several validators is one attempt, clean only if all are; a
  run whose result is missing or unrecognised is `unknown`, never clean. The
  overall column pools every run's attempts before taking the median.
- **Cost** — median Copilot **AI credits** per run (what the org is billed;
  differs ~40× between the cheapest and most expensive models), premium
  requests, and the token split (I/CW/CR/O), from `--usage-output-file`.
- **Time** — median Copilot session wall-clock (excludes CLI install, sandbox
  setup, and scoring; runner-noisy).

No pass/fail gate and no baselines (both are model-specific); failing samples
are data. There's no automatic recommendation — read the matrix. Samples are
few, so treat small differences as noise.

**Known limitation.** `camunda-ai-agents` offers react agents a host-side
`request_configuration` tool that Copilot can't see, so its
`configuration_requested` samples aren't comparable under Copilot.

**Cost of a run.** Copilot starts one session per dataset sample per epoch, so a
run is *Σ samples of the selected targets × models × epochs* sessions — not
targets. The outcome evals hold ~33 samples today (camunda-development alone has
7), so a full default run is ~33 × 5 × 3 ≈ 500 sessions. Start with `target` and
fewer models/epochs.

**Re-runs.** Re-running failed jobs is safe: the matrix keeps only the newest log
per eval × model, and the artifact is overwritten. A run interrupted by a time
limit still records its transcript and the credits spent so far (from Copilot's
usage checkpoints). Its tokens are unknown and left out of token medians; the
report counts such runs and marks affected cost cells `†`.

## Credentials & secrets

The model id is configuration. CI defaults to `anthropic/claude-sonnet-4-6`
(Inspect's `anthropic` provider), switchable in one place — the `EVAL_MODEL` repo
variable. The workflows read:

| Kind | Name | Purpose |
|---|---|---|
| Secret | `ANTHROPIC_API_KEY` | model auth |
| Variable | `EVAL_MODEL` | optional — overrides the CI model id |

Set these under **Settings → Secrets and variables → Actions**. `ANTHROPIC_API_KEY`
is read by Inspect on the runner; the sandbox bridge proxies model calls back to
it, so the container carries no credential. Point `EVAL_MODEL` at another provider
and swap the credential env in the run step.

## Cost controls

- Each sample runs once by default. Use `--epochs` only with evidence of flake.
- Per-task `time_limit` lives in the eval's `outcomes.py`; per-container
  memory/CPU caps in the relevant `evals/sandboxes/compose-*.yaml`.
- The PR comment surfaces token-budget excursions (observed vs `baseline × 1.5`)
  — a systematic blow-up is a regression signal; investigate before regenerating.

## Not yet built

Deferred follow-ups — opened as PRs when their trigger fires, not pre-fabricated:

- **Re-enable the nightly cron** (currently `workflow_dispatch`-only).
- **Monthly model matrix** — uncomment the `schedule` in `eval-models.yml`.
- **Cross-harness matrix** — compare `react` and `copilot_cli` on the same
  model (both agent loops now exist).
- **Assertion-hygiene check** — flag always-pass / always-fail scorers.
- **A/B comparison** between skill versions; **static-export Inspect view** to
  GitHub Pages.
