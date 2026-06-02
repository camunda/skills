# Eval suite — CI & results

How evals run in CI, what the PR comment looks like, and how to debug
a failure from a CI artifact.

## Day-to-day: a skill-change PR

The common path when you edit a `skills/<X>/SKILL.md` or its `references/`:

1. **Iterate locally** — `make eval-triggers SKILL=<X>` for routing,
   `make eval-outcomes TARGET=skills/<X>` for behaviour. See the
   [runbook](runbook.md) for the local loop.
2. **Open the PR.** Nothing runs automatically — `eval.yml` is opt-in and
   maintainer-gated (see [Workflows](#workflows)).
3. **A maintainer adds `evals:run`** — runs the targets your change can
   affect, on the `with_skill` arm, gated against the committed baseline, and
   posts the rolling comment.
4. **Read the result** — the PR comment for the verdict, the run's job summary
   for token usage, the trajectory viewer for a failing sample.
5. **Occasionally** add `evals:compare` (does the skill earn its keep — the
   with-vs-without delta) or `evals:run-all` (whole-suite check). Labels re-run
   on each push while present; remove to stop.
6. **Intentional behaviour change that moved tokens?** Regenerate the baseline
   locally and commit the reviewed diff (`make eval-baseline TARGET=…`) — never
   to make CI green.

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

Labels make two **orthogonal** choices — **scope** (which targets) and **arms**
(whether to also run the without-skill comparison). They re-run on each push
while present; remove to stop.

**Scope** — pick one:

- **`evals:run`** — targets whose skills intersect the changed skills
  (`metadata.skills ∩ changed-skills ≠ ∅`, via `evals-list --changed-skills`).
  The everyday PR signal.
- **`evals:run-all`** — every target. Whole-suite integration check, e.g. for
  harness/plumbing changes.

**Arms** — optional, combine with either scope label:

- **`evals:compare`** — also run the `without_skill` arm of outcome evals (the
  with-vs-without delta). Without it, outcome evals run `with_skill` only.

| You want to… | Label(s) | Runs | Gated vs baseline? |
|---|---|---|---|
| Check the skills your PR touched | `evals:run` | affected targets, `with_skill` | ✅ yes |
| Check the whole suite | `evals:run-all` | every target, `with_skill` | ✅ yes |
| See what a skill *adds* | either **+ `evals:compare`** | adds the `without_skill` arm | `with_skill` ✅ · `without_skill` ❌ never |

So `evals:run-all` alone runs every target on `with_skill` only; you add
`evals:compare` to get the second arm.

### Arms & the baseline

Only **outcome evals** have arms; a trigger is a single routing call with no
arm and no baseline.

- **`with_skill`** — every skill available (the real condition). The **gated**
  arm: in the `Gate (evals-pass-fail)` step each sample must pass its gating
  scorers *and* stay within its token budget (`baseline × 1.5`, from the
  committed `outcomes_baseline.json`).
- **`without_skill`** — the skill(s) named in the eval's
  `METADATA.baseline.exclude` are disabled; everything else stays. Runs **only**
  under `evals:compare`, is **never gated** (it's the comparison, not a bar),
  and feeds the comment's "Skill impact" delta.

So the baseline is compared in exactly one place — the `with_skill` arm of
outcome evals. Triggers and the `without_skill` arm never touch it.

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
`trigger:camunda-feel`, `skill:camunda-feel`, or
`scenario:rocket-launch` and `kind` is `trigger | outcome` (the `skill:`
/ `scenario:` id prefix is just the outcome eval's scope). Adding a
target needs no workflow change — selection falls out of `metadata.skills`
(the skill dir name for triggers).

## Job summary & PR comment

`evals/src/scripts/summarize.py` renders one Markdown report to two
surfaces (lean for the PR, detailed for the run page):

- **Job summary** (`$GITHUB_STEP_SUMMARY`) — every run (PR or
  `workflow_dispatch`). Rendered with `--detail`, which adds a per-eval
  **`Tokens`** column (total tokens with an `[I/CW/CR/O]` split) to the
  outcome and trigger tables. This is the deep-dive surface and is also
  saved into the consolidated artifact as `summary.md`.
- **PR comment** — pull requests only. The lean render (no `Tokens`
  column). One rolling comment: a `find-comment` step locates the prior
  one by a hidden marker (`<!-- camunda-skills-eval-comment -->`, which
  the workflow prepends — not the script) and `create-or-update-comment`
  replaces it in place, not stacked.

Shape — a headline verdict, the model + run-wide token usage (total with
the `[I/CW/CR/O]` split), an outcome table (verdict + observed tokens vs
`baseline × 1.5`), a trigger routing table, a "Skill impact" delta when
the `without_skill` arm ran, and — under `--detail` — a `Tokens` column
on the two tables:

```
### 🧪 Eval results

**Triggers 13/13 · Outcomes 4/4** — ✅ all passed. Non-blocking signal (doesn't block merge).

Model `anthropic/bedrock/global.anthropic.claude-sonnet-4-6` · 1,315,560 tokens [I: 86,703, CW: 156,885, CR: 1,045,395, O: 26,577]
_I input · CW cache-write · CR cache-read · O output._

#### Outcome evals          (--detail adds the Tokens column)
| Eval         | Outcome      | Tokens vs baseline     | Tokens                                                       |
| ------------ | ------------ | ---------------------- | ------------------------------------------------------------ |
| camunda-feel | ✅ 3/3 (100%) | ✅ 89k (+0% vs 89k)     | 89,402 tokens [I: 1,204, CW: 6,012, CR: 79,610, O: 2,576]    |
| rocket-launch| ✅ 1/1 (100%) | 🔴 480k (+45% vs 331k) | 480,114 tokens [I: 9,330, CW: 41,002, CR: 421,560, O: 8,222] |

#### Trigger evals (skill routing)
| Skill        | Routing       | Tokens                                              |
| ------------ | ------------- | --------------------------------------------------- |
| camunda-bpmn | ⚠️ 3/4 (75%)  | 33,120 tokens [I: 412, CW: 2,103, CR: 30,210, O: 395] |

#### Skill impact (with vs without)
- **camunda-feel**: with-skill 100% vs without-skill 50% (Δ +50%)
```

Tables are column-aligned in the source so the same output is readable
on a CLI (`uv run evals-summarize --log-dir <dir>`; add `--detail` for the
`Tokens` column). The report is a summary; the trajectory viewer is the
debugger (see below). For the per-sample scorer + token-budget breakdown,
run `evals-pass-fail` (or `make eval-viewer`) against the logs.

## Artifacts

Each run publishes **one** consolidated artifact, `eval-logs-<sha>`,
holding every `.eval` log plus the rendered `summary.md` (retention: 30
days on PR runs, 14 nightly):

```
evals/logs/
├── <timestamp>_<eval>_<id>.eval     # one per target × arm
├── …
└── summary.md                       # the --detail report
```

Download it all at once (`gh run download <run-id>`) or open the
trajectory viewer over it (below). The matrix also leaves short-lived
per-job `eval-logs-<slug>-<attempt>` artifacts (1-day retention) that
`summarize` collects into the consolidated one — ignore them; they
expire on their own.

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
   make eval-triggers SKILL=<name>    # trigger
   make eval-outcomes TARGET=<dir>    # outcome eval (skill or scenario dir)
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
  make eval-triggers SKILL=camunda-feel MODEL=anthropic/bedrock/global.anthropic.claude-sonnet-4-6
```

A trigger eval is the cheapest smoke — no cluster boot. The judge
outcome eval `make eval-outcomes TARGET=skills/camunda-development` is the next
step up (also no cluster). A clean exit with a scored sample confirms
the credentials and model resolve. Drop the `MODEL=` override to use the
local default (`anthropic/claude-sonnet-4-6` + `ANTHROPIC_API_KEY`).

## Cost controls

- Each sample runs once by default. Use Inspect's `--epochs` only with
  evidence of flake — don't pay for repeats by default.
- `time_limit` per task is set via Inspect's task-level config, in the
  eval's `outcomes.py`.
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
