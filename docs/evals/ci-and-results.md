# Eval suite — CI & results

How evals run in CI, what the PR comment looks like, and how to debug
a failure from a CI artifact.

## Workflows

| Workflow | Trigger | Scope |
|---|---|---|
| `.github/workflows/lint.yml` (existing) | PR touching `skills/**` or `.waza.yaml` | `waza check` only |
| `.github/workflows/eval.yml` | PR touching `skills/<X>/**` or `evals/**`, or PR labeled `evals:run` | Scenarios where `metadata.skills ∩ changed-skills ≠ ∅` |
| `.github/workflows/eval-nightly.yml` | Schedule (nightly) on `main` | All scenarios in all tiers |

PR filter via `dorny/paths-filter`. Path-filter inclusion is
automatic from `metadata.skills` — there's no separate workflow
matrix to keep in sync.

## Tier matrix

| Tier | Runs on | What |
|---|---|---|
| `pr` | PR + nightly | All scenarios in v1 are PR-tier |
| `nightly` | Nightly only | Reserved for slow/expensive scenarios as they appear |
| `release` | On `v*` tags (future) | Full release-gate suite |

To add a scenario to a tier, set `metadata.tier` in `task.py`. No
workflow changes needed.

## PR comment

Posted via `peter-evans/create-or-update-comment@v4` with
`edit-mode: replace` — one rolling comment per PR, not stacked.

Shape (rendered by `evals/src/eval_harness/scripts/summarize.py`):

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

- **Copilot CLI** (default agent): no repo secret needed. The
  workflow grants `permissions: { models: read }` and the
  auto-injected `GITHUB_TOKEN` covers both the agent and the judge.
- **Claude Code** (`INSPECT_AGENT_BRIDGE=claude-code`): requires
  `ANTHROPIC_API_KEY` repo secret. Currently used only for the
  weekly cross-harness matrix (`FOLLOWUP-EVAL-02`); not wired up
  in v1.

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
