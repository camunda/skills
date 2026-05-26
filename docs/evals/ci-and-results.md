# Eval suite — CI & results

How evals run in CI, what the PR comment looks like, and how to debug
a failure from a CI artifact.

## Workflows

| Workflow | Today's trigger | Designed scope |
|---|---|---|
| `.github/workflows/lint.yml` (existing) | PR touching `skills/**` or `.waza.yaml` | `waza check` only |
| `.github/workflows/eval.yml` | **`workflow_dispatch` only** (gated until credentials land) | When turned on: PR touching `skills/<X>/**` or `evals/**`, or PR labeled `evals:run`; runs scenarios where `metadata.skills ∩ changed-skills ≠ ∅` |
| `.github/workflows/eval-nightly.yml` | **`workflow_dispatch` only** (gated until credentials land) | When turned on: nightly schedule on `main`; runs all scenarios in all tiers |

PR filter via `dorny/paths-filter`. Path-filter inclusion is
automatic from `metadata.skills` (resolved by `evals-list
--changed-skills`); no separate workflow matrix to keep in sync. The
workflows live in the repo today so the wiring is reviewable, but
they don't fire on PRs until credentials are provisioned and at least
one more scenario validates against the harness.

## Tier matrix

| Tier | Runs on (when CI is enabled) | What |
|---|---|---|
| `pr` | PR + nightly | Default for fast / low-cost scenarios |
| `nightly` | Nightly only | Slow / expensive / deferred scenarios (e.g. AI-agent scenarios pending mocking + cost decisions) |
| `release` | On `v*` tags (future) | Full release-gate suite |

To add a scenario to a tier, set `metadata.tier` in `task.py`. No
workflow changes needed.

## PR comment

Posted via `peter-evans/create-or-update-comment@v4` with
`edit-mode: replace` — one rolling comment per PR, not stacked.

Shape (rendered by `evals/src/scripts/summarize.py`):

```
### 🧪 Eval results

| Scenario | with-skill | without-skill | Δ tokens | Δ duration |
|---|---|---|---|---|
| c8ctl-bootstrap | ✅ 1/1 | — | — | — |
| rocket-launch | ✅ 1/1 (4.2k tok, 12s) | ❌ 0/1 | -- | -- |

**Cost**: $0.18 (budget: $1–4)
**Logs**: [eval-<sha>.zip](workflow-artifact-url)

<details>
<summary>Baseline comparison</summary>

| Scenario | Field | Baseline | Run | Status |
|---|---|---|---|---|
| rocket-launch | tokens | 3500–6500 | 4180 | ✅ in band |
| rocket-launch | duration_s | 8–25 | 12 | ✅ in band |

</details>
```

The comment is a summary. The trajectory viewer is the debugger
(see below).

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
   non-determinism (mitigated by `epochs` ≥ 3 for trigger/judge
   scenarios).

## Credentials & secrets

The eval workflows are currently `workflow_dispatch`-only because the
credential path isn't decided yet. Options:

- **Anthropic direct** — `ANTHROPIC_API_KEY` as a repo secret; Inspect
  invoked with `--model anthropic/claude-sonnet-4-6`.
- **AWS Bedrock** — `AWS_*` secrets (or OIDC role assumption) for the
  Bedrock provider; Inspect with `--model bedrock/<inference-profile>`.
- **GitHub Models (paid)** — `models: read` permission on
  `GITHUB_TOKEN` covers the agent + judge in a single line item. The
  free tier was tested and rejected (per-request token caps too tight
  for the `react()` loop with `skill()` + 13 skills).

Whichever path is picked, the workflows' `on:` block flips from
`workflow_dispatch` to `pull_request` / `schedule` and the
`Run scenario` step injects the credentials via env. The shape of
`detect-scenarios` and `summarize` doesn't change.

## Cost controls

- `metadata.epochs` defaults to `1` for hard-fact scenarios. Don't
  bump without evidence of flake.
- `time_limit` per task is set via Inspect's task-level config.
  Per-scenario in `task.py`.
- Compose `deploy.resources.limits` cap memory/CPU per container.
  Adjust in `evals/sandboxes/compose.yaml` if a scenario legitimately
  needs more.
- The PR comment surfaces cost-band excursions. If a scenario
  systematically blows its band, that's a regression signal —
  investigate before regenerating the baseline.

## What's not in v1

The plan defers these to follow-ups (see
[`docs/plans/01-eval-suite.md`](../plans/01-eval-suite.md)):

- Cross-harness weekly matrix → `FOLLOWUP-EVAL-02`
- Quarterly assertion hygiene cron → `FOLLOWUP-EVAL-03`
- A/B comparison between skill versions → `FOLLOWUP-EVAL-05`
- Static-export Inspect view to GitHub Pages → `FOLLOWUP-EVAL-06`

Open them as PRs when their trigger fires.
